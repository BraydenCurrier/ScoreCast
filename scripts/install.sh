#!/usr/bin/env bash
set -Eeuo pipefail

# ScoreCast fresh-install script for Raspberry Pi OS Lite (64-bit).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/BraydenCurrier/ScoreCast/main/scripts/install.sh | sudo bash
#
# Optional environment variables:
#   SCORECAST_REPO_URL=https://github.com/BraydenCurrier/ScoreCast.git
#   SCORECAST_INSTALL_DIR=/opt/scorecast
#   SCORECAST_STATE_DIR=/var/lib/scorecast
#   SCORECAST_SERVICE_NAME=scorecast
#   SCORECAST_UPDATE_SERVICE_NAME=scorecast-update
#   SCORECAST_RGB_MATRIX_DIR=/opt/rpi-rgb-led-matrix
#   SCORECAST_VERSION=v1.0.5
#
# If SCORECAST_VERSION is omitted, the newest semantic-version tag is installed.

REPO_URL="${SCORECAST_REPO_URL:-https://github.com/BraydenCurrier/ScoreCast.git}"
INSTALL_DIR="${SCORECAST_INSTALL_DIR:-/opt/scorecast}"
STATE_DIR="${SCORECAST_STATE_DIR:-/var/lib/scorecast}"
SERVICE_NAME="${SCORECAST_SERVICE_NAME:-scorecast}"
UPDATE_SERVICE_NAME="${SCORECAST_UPDATE_SERVICE_NAME:-scorecast-update}"
RGB_MATRIX_DIR="${SCORECAST_RGB_MATRIX_DIR:-/opt/rpi-rgb-led-matrix}"
REQUESTED_TAG="${SCORECAST_VERSION:-}"

REPO_DIR="${INSTALL_DIR}/repo.git"
RELEASES_DIR="${INSTALL_DIR}/releases"
VENVS_DIR="${INSTALL_DIR}/venvs"

CURRENT_LINK="${INSTALL_DIR}/current"
PREVIOUS_LINK="${INSTALL_DIR}/previous"
CURRENT_VENV_LINK="${INSTALL_DIR}/current-venv"
PREVIOUS_VENV_LINK="${INSTALL_DIR}/previous-venv"

STATUS_FILE="${INSTALL_DIR}/update-status.json"
LOCK_FILE="${INSTALL_DIR}/install.lock"

SYSTEMD_DIR="/etc/systemd/system"
MAIN_SERVICE_FILE="${SYSTEMD_DIR}/${SERVICE_NAME}.service"
UPDATE_SERVICE_FILE="${SYSTEMD_DIR}/${UPDATE_SERVICE_NAME}.service"

RESUME_MARKER="/var/lib/scorecast/install-resume.pending"
RESUME_SCRIPT="/usr/local/sbin/scorecast-install-resume"
RESUME_SERVICE="/etc/systemd/system/scorecast-install-resume.service"
AUDIO_BLACKLIST="/etc/modprobe.d/scorecast-audio.conf"

APT_PACKAGES=(
    git
    curl
    ca-certificates
    python3
    python3-pip
    python3-venv
    python3-dev
    python3-pil
    cython3
    cmake
    ninja-build
    build-essential
    libjpeg-dev
    zlib1g-dev
    libopenjp2-7-dev
    libtiff-dev
    libfreetype6-dev
    liblcms2-dev
    libwebp-dev
    libharfbuzz-dev
    libfribidi-dev
    libxcb1-dev
    libssl-dev
)
log() {
    printf '\n[ScoreCast installer] %s\n' "$*"
}

die() {
    printf '\n[ScoreCast installer] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "Run this installer as root, for example: sudo bash scripts/install.sh"
    fi
}

cleanup() {
    rm -f "${LOCK_FILE}" 2>/dev/null || true
}

trap cleanup EXIT
trap 'die "Installation stopped unexpectedly near line ${LINENO}."' ERR

acquire_lock() {
    mkdir -p "${INSTALL_DIR}"

    if [[ -e "${LOCK_FILE}" ]]; then
        die "Another ScoreCast installation appears to be running: ${LOCK_FILE}"
    fi

    printf '%s\n' "$$" > "${LOCK_FILE}"
}

install_os_packages() {
    log "Updating package lists."
    apt-get update

    log "Installing operating-system dependencies."
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
}

get_boot_config_path() {
    if [[ -f /boot/firmware/config.txt ]]; then
        printf '%s\n' "/boot/firmware/config.txt"
        return 0
    fi

    if [[ -f /boot/config.txt ]]; then
        printf '%s\n' "/boot/config.txt"
        return 0
    fi

    return 1
}

rgb_matrix_audio_conflict_present() {
    grep -q '^snd_bcm2835 ' /proc/modules 2>/dev/null
}

disable_builtin_audio() {
    local boot_config

    boot_config="$(get_boot_config_path)" || {
        die "Could not find Raspberry Pi config.txt."
    }

    log "Disabling Raspberry Pi built-in audio for the RGB matrix."

    cp -a \
        "${boot_config}" \
        "${boot_config}.scorecast-backup"

    # Replace active audio=on entries.
    sed -i \
        -E 's/^[[:space:]]*dtparam=audio=on[[:space:]]*$/dtparam=audio=off/' \
        "${boot_config}"

    # Add audio=off when it is not already present.
    if ! grep -Eq \
        '^[[:space:]]*dtparam=audio=off[[:space:]]*$' \
        "${boot_config}"; then

        {
            printf '\n'
            printf '# ScoreCast RGB matrix configuration\n'
            printf 'dtparam=audio=off\n'
        } >> "${boot_config}"
    fi

    # Prevent the conflicting kernel module from loading.
    cat > "${AUDIO_BLACKLIST}" <<'EOF'
# ScoreCast uses the Raspberry Pi hardware timing subsystem for the RGB matrix.
blacklist snd_bcm2835
EOF

    log "Built-in Raspberry Pi audio has been disabled."
}

install_resume_helper() {
    log "Installing the one-time post-reboot setup helper."

    install -d \
        -m 0755 \
        /var/lib/scorecast

    touch "${RESUME_MARKER}"
    chmod 0644 "${RESUME_MARKER}"

    cat > "${RESUME_SCRIPT}" <<'EOF'
#!/usr/bin/env bash

set -Eeuo pipefail

MARKER="/var/lib/scorecast/install-resume.pending"
STATUS_FILE="/opt/scorecast/update-status.json"
SERVICE_NAME="scorecast"
DASHBOARD_URL="http://127.0.0.1:8080/"
MAX_ATTEMPTS=30
SLEEP_SECONDS=2

log() {
    printf '\n[ScoreCast resume] %s\n' "$*"
}

write_status() {
    local state="$1"
    local message="$2"

    python3 - "${STATUS_FILE}" "${state}" "${message}" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

path, state, message = sys.argv[1:4]

data = {
    "state": state,
    "message": message,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

directory = os.path.dirname(path)
os.makedirs(directory, exist_ok=True)

fd, temporary_path = tempfile.mkstemp(
    dir=directory,
    prefix=".update-status.",
    suffix=".tmp",
)

try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(temporary_path, path)
except Exception:
    try:
        os.unlink(temporary_path)
    except FileNotFoundError:
        pass
    raise
PY
}

fail() {
    local message="$1"

    log "ERROR: ${message}"
    write_status "error" "${message}"
    exit 1
}

if [[ ! -e "${MARKER}" ]]; then
    log "No pending installation was found."
    exit 0
fi

if grep -q '^snd_bcm2835 ' /proc/modules 2>/dev/null; then
    fail "snd_bcm2835 is still loaded after reboot."
fi

if [[ ! -x /opt/scorecast/current-venv/bin/python ]]; then
    fail "The active ScoreCast Python environment is missing."
fi

if [[ ! -f /opt/scorecast/current/src/main.py ]]; then
    fail "The active ScoreCast release is missing src/main.py."
fi

log "Starting ScoreCast after reboot."

systemctl reset-failed "${SERVICE_NAME}" || true
systemctl restart "${SERVICE_NAME}"

for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if curl \
        --fail \
        --silent \
        --show-error \
        --max-time 3 \
        "${DASHBOARD_URL}" \
        >/dev/null 2>&1; then

        log "ScoreCast is healthy."

        rm -f "${MARKER}"
        write_status \
            "success" \
            "ScoreCast installation completed successfully after reboot."

        systemctl disable scorecast-install-resume.service \
            >/dev/null 2>&1 || true

        exit 0
    fi

    sleep "${SLEEP_SECONDS}"
done

journalctl \
    -u "${SERVICE_NAME}" \
    -n 50 \
    --no-pager || true

fail "ScoreCast did not become healthy after reboot."
EOF

    chmod 0755 "${RESUME_SCRIPT}"
}

install_resume_service() {
    log "Installing the one-time post-reboot systemd service."

    cat > "${RESUME_SERVICE}" <<EOF
[Unit]
Description=Complete ScoreCast installation after reboot
Wants=network-online.target
After=network-online.target
ConditionPathExists=${RESUME_MARKER}

[Service]
Type=oneshot
ExecStart=${RESUME_SCRIPT}
RemainAfterExit=no
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable scorecast-install-resume.service
}

schedule_installation_reboot() {
    log "A reboot is required to finish the ScoreCast installation."

    printf '\n'
    printf '%s\n' "============================================================"
    printf '%s\n' " ScoreCast has been installed."
    printf '%s\n' " Built-in Raspberry Pi audio has been disabled."
    printf '%s\n' " The installation will finish automatically after reboot."
    printf '%s\n' "============================================================"
    printf '\n'

    sync

    if [[ -t 0 && -t 1 ]]; then
        read -r -p "Press Enter to reboot now, or Ctrl+C to reboot later. "
    else
        log "Rebooting automatically."
        sleep 5
    fi

    systemctl reboot
    exit 0
}

prepare_directories() {
    log "Preparing ScoreCast directories."

    mkdir -p \
        "${INSTALL_DIR}" \
        "${RELEASES_DIR}" \
        "${VENVS_DIR}" \
        "${STATE_DIR}"

    chown root:root "${INSTALL_DIR}" "${RELEASES_DIR}" "${VENVS_DIR}" "${STATE_DIR}"
    chmod 0755 "${INSTALL_DIR}" "${RELEASES_DIR}" "${VENVS_DIR}"
    chmod 0700 "${STATE_DIR}"
}

prepare_repository() {
    if [[ ! -d "${REPO_DIR}" ]]; then
        log "Cloning ScoreCast repository."
        git clone --bare "${REPO_URL}" "${REPO_DIR}"
    else
        log "Using existing ScoreCast repository."
    fi

    log "Fetching branches and release tags."
    git \
        --git-dir="${REPO_DIR}" \
        fetch \
        --prune \
        --tags \
        origin
}

version_key() {
    local tag="${1#v}"
    printf '%s\n' "${tag}"
}

select_release_tag() {
    if [[ -n "${REQUESTED_TAG}" ]]; then
        if ! git --git-dir="${REPO_DIR}" rev-parse --verify --quiet "${REQUESTED_TAG}^{commit}" >/dev/null; then
            die "Requested release tag does not exist: ${REQUESTED_TAG}"
        fi

        RELEASE_TAG="${REQUESTED_TAG}"
        return
    fi

    RELEASE_TAG="$(
        git \
            --git-dir="${REPO_DIR}" \
            tag \
            --list 'v[0-9]*.[0-9]*.[0-9]*' \
            --sort=-version:refname \
        | head -n 1
    )"

    [[ -n "${RELEASE_TAG}" ]] || die "No semantic-version release tags were found."

    log "Latest release is ${RELEASE_TAG}."
}

checkout_release() {
    RELEASE_VERSION="${RELEASE_TAG#v}"
    RELEASE_DIR="${RELEASES_DIR}/${RELEASE_VERSION}"

    if [[ -d "${RELEASE_DIR}" ]]; then
        if [[ -f "${RELEASE_DIR}/src/main.py" && -f "${RELEASE_DIR}/requirements.txt" ]]; then
            log "Release ${RELEASE_VERSION} is already checked out."
            return
        fi

        log "Removing incomplete release directory."
        git \
            --git-dir="${REPO_DIR}" \
            worktree remove \
            --force \
            "${RELEASE_DIR}" \
            2>/dev/null \
            || rm -rf "${RELEASE_DIR}"
    fi

    log "Checking out ${RELEASE_TAG}."
    git \
        --git-dir="${REPO_DIR}" \
        worktree add \
        --detach \
        "${RELEASE_DIR}" \
        "${RELEASE_TAG}"

    [[ -f "${RELEASE_DIR}/src/main.py" ]] \
        || die "Release is missing src/main.py."

    [[ -f "${RELEASE_DIR}/requirements.txt" ]] \
        || die "Release is missing requirements.txt."

    [[ -f "${RELEASE_DIR}/src/updater/updater.py" ]] \
        || die "Release is missing src/updater/updater.py."
}

install_rgb_matrix_library() {
    log "Downloading the RGB matrix library."

    if [[ ! -d "${RGB_MATRIX_DIR}/.git" ]]; then
        rm -rf "${RGB_MATRIX_DIR}"

        git clone \
            https://github.com/hzeller/rpi-rgb-led-matrix.git \
            "${RGB_MATRIX_DIR}"
    else
        git -C "${RGB_MATRIX_DIR}" fetch --prune origin
        git -C "${RGB_MATRIX_DIR}" reset --hard origin/master
    fi

    log "Building the RGB matrix C++ examples."

    make \
        -C "${RGB_MATRIX_DIR}" \
        -j"$(nproc)"
}

create_release_venv() {
    VENV_DIR="${VENVS_DIR}/${RELEASE_VERSION}"
    VENV_PYTHON="${VENV_DIR}/bin/python"
    VENV_PIP="${VENV_DIR}/bin/pip"

    if [[ ! -x "${VENV_PYTHON}" ]]; then
        log "Creating Python environment for ${RELEASE_VERSION}."
        rm -rf "${VENV_DIR}"
        python3 -m venv --system-site-packages "${VENV_DIR}"
    else
        log "Using existing Python environment for ${RELEASE_VERSION}."
    fi

    log "Installing Python dependencies."
    "${VENV_PYTHON}" -m pip install \
        --disable-pip-version-check \
        --upgrade \
        pip \
        setuptools \
        wheel

    "${VENV_PIP}" install \
        --disable-pip-version-check \
        -r "${RELEASE_DIR}/requirements.txt"

    log "Installing the RGB matrix Python binding."

    "${VENV_PIP}" install \
        --disable-pip-version-check \
        "${RGB_MATRIX_DIR}"

    log "Verifying the RGB matrix Python binding."
    if ! "${VENV_PYTHON}" -c 'import rgbmatrix' >/dev/null 2>&1; then
        die "The rgbmatrix Python binding could not be imported from ${VENV_DIR}."
    fi
}

validate_release() {
    log "Validating ScoreCast release ${RELEASE_VERSION}."

    SCORECAST_CONFIG_DIR="${STATE_DIR}" \
    PYTHONPATH="${RELEASE_DIR}/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    "${VENV_PYTHON}" \
        -m compileall \
        -q \
        "${RELEASE_DIR}/src"

    SCORECAST_CONFIG_DIR="${STATE_DIR}" \
    PYTHONPATH="${RELEASE_DIR}/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    "${VENV_PYTHON}" - <<'PY'
from common.settings import get_settings
from common.matrix import create_matrix
from web.app import app

settings = get_settings()

assert isinstance(settings, dict)
assert callable(create_matrix)
assert app is not None

print("ScoreCast release validation succeeded.")
PY
}

replace_symlink() {
    local link_path="$1"
    local target_path="$2"
    local temporary_link="${link_path}.new"

    rm -f "${temporary_link}"
    ln -s "${target_path}" "${temporary_link}"
    mv -Tf "${temporary_link}" "${link_path}"
}

activate_release() {
    log "Activating release ${RELEASE_VERSION}."

    local old_release=""
    local old_venv=""

    if [[ -L "${CURRENT_LINK}" ]]; then
        old_release="$(readlink -f "${CURRENT_LINK}" || true)"
    fi

    if [[ -L "${CURRENT_VENV_LINK}" ]]; then
        old_venv="$(readlink -f "${CURRENT_VENV_LINK}" || true)"
    fi

    if [[ -n "${old_release}" && -d "${old_release}" ]]; then
        replace_symlink "${PREVIOUS_LINK}" "${old_release}"
    else
        replace_symlink "${PREVIOUS_LINK}" "${RELEASE_DIR}"
    fi

    if [[ -n "${old_venv}" && -d "${old_venv}" ]]; then
        replace_symlink "${PREVIOUS_VENV_LINK}" "${old_venv}"
    else
        replace_symlink "${PREVIOUS_VENV_LINK}" "${VENV_DIR}"
    fi

    replace_symlink "${CURRENT_LINK}" "${RELEASE_DIR}"
    replace_symlink "${CURRENT_VENV_LINK}" "${VENV_DIR}"
}

install_systemd_services() {
    log "Installing systemd services."

    if [[ -f "${RELEASE_DIR}/systemd/scorecast.service" ]]; then
        install -o root -g root -m 0644 \
            "${RELEASE_DIR}/systemd/scorecast.service" \
            "${MAIN_SERVICE_FILE}"
    else
        cat > "${MAIN_SERVICE_FILE}" <<EOF
[Unit]
Description=ScoreCast LED Sports Ticker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root

WorkingDirectory=${CURRENT_LINK}
ExecStart=${CURRENT_VENV_LINK}/bin/python ${CURRENT_LINK}/src/main.py

Restart=always
RestartSec=3

StateDirectory=scorecast
StateDirectoryMode=0700
ReadWritePaths=${STATE_DIR}

Environment=SCORECAST_CONFIG_DIR=${STATE_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    fi

    if [[ -f "${RELEASE_DIR}/systemd/scorecast-update.service" ]]; then
        install -o root -g root -m 0644 \
            "${RELEASE_DIR}/systemd/scorecast-update.service" \
            "${UPDATE_SERVICE_FILE}"
    else
        cat > "${UPDATE_SERVICE_FILE}" <<EOF
[Unit]
Description=Update ScoreCast from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
Group=root

WorkingDirectory=${CURRENT_LINK}
ExecStart=${CURRENT_VENV_LINK}/bin/python -m updater.updater

Environment=PYTHONPATH=${CURRENT_LINK}/src
Environment=SCORECAST_CONFIG_DIR=${STATE_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

StandardOutput=journal
StandardError=journal

TimeoutStartSec=15min
EOF
    fi

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
}

initialize_status_file() {
    if [[ -f "${STATUS_FILE}" ]]; then
        return
    fi

    cat > "${STATUS_FILE}" <<EOF
{
  "state": "current",
  "message": "ScoreCast ${RELEASE_VERSION} is installed.",
  "version": "${RELEASE_VERSION}",
  "updated_at": ""
}
EOF

    chown root:root "${STATUS_FILE}"
    chmod 0644 "${STATUS_FILE}"
}

start_and_verify() {
    log "Preparing to start ScoreCast."

    systemctl enable "${SERVICE_NAME}.service"

    if rgb_matrix_audio_conflict_present; then
        log "The Raspberry Pi built-in audio module conflicts with the RGB matrix."

        systemctl stop "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
        systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true

        disable_builtin_audio
        install_resume_helper
        install_resume_service
        schedule_installation_reboot

        return
    fi

    log "Starting ScoreCast."

    systemctl restart "${SERVICE_NAME}.service"

    local deadline=$((SECONDS + 45))

    while (( SECONDS < deadline )); do
        if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
            if curl \
                --silent \
                --show-error \
                --fail \
                --max-time 3 \
                http://127.0.0.1:8080/ \
                >/dev/null 2>&1; then

                log "ScoreCast is running and the dashboard is responding."

                rm -f "${RESUME_MARKER}"

                systemctl disable scorecast-install-resume.service \
                    >/dev/null 2>&1 || true

                return
            fi
        fi

        sleep 1
    done

    systemctl status "${SERVICE_NAME}.service" --no-pager || true
    journalctl \
        -u "${SERVICE_NAME}.service" \
        -n 100 \
        --no-pager || true

    die "ScoreCast did not become healthy after installation."
}

print_summary() {
    local ip_address
    ip_address="$(hostname -I 2>/dev/null | awk '{print $1}')"

    printf '\n'
    printf 'ScoreCast %s installed successfully.\n' "${RELEASE_VERSION}"
    printf '\n'
    printf 'Dashboard: http://%s:8080\n' "${ip_address:-<raspberry-pi-ip>}"
    printf 'Current release: %s\n' "$(readlink -f "${CURRENT_LINK}")"
    printf 'Settings: %s/settings.json\n' "${STATE_DIR}"
    printf '\n'
    printf 'Useful commands:\n'
    printf '  sudo systemctl status %s --no-pager\n' "${SERVICE_NAME}"
    printf '  sudo journalctl -u %s -f\n' "${SERVICE_NAME}"
    printf '  sudo systemctl start %s\n' "${UPDATE_SERVICE_NAME}"
    printf '\n'
}

main() {
    require_root
    acquire_lock
    install_os_packages
    prepare_directories
    prepare_repository
    select_release_tag
    checkout_release
    install_rgb_matrix_library
    create_release_venv
    validate_release
    activate_release
    install_systemd_services
    initialize_status_file
    start_and_verify
    print_summary
}

main "$@"
