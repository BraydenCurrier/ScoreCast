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

APT_PACKAGES=(
    git
    curl
    ca-certificates
    python3
    python3-pip
    python3-venv
    python3-dev
    build-essential
    libjpeg-dev
    zlib1g-dev
    libopenjp2-7-dev
    libtiff-dev
    libatlas-base-dev
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
    log "Installing the RGB matrix library."

    if [[ ! -d "${RGB_MATRIX_DIR}/.git" ]]; then
        rm -rf "${RGB_MATRIX_DIR}"
        git clone https://github.com/hzeller/rpi-rgb-led-matrix.git "${RGB_MATRIX_DIR}"
    else
        git -C "${RGB_MATRIX_DIR}" fetch --prune origin
        git -C "${RGB_MATRIX_DIR}" reset --hard origin/master
    fi

    make -C "${RGB_MATRIX_DIR}" -j"$(nproc)"
    make -C "${RGB_MATRIX_DIR}" build-python
    make -C "${RGB_MATRIX_DIR}" install-python
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
                return
            fi
        fi

        sleep 1
    done

    systemctl status "${SERVICE_NAME}.service" --no-pager || true
    journalctl -u "${SERVICE_NAME}.service" -n 100 --no-pager || true

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
