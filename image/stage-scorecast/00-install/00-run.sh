
#!/bin/bash -e
set -euo pipefail

# ==========================================
# ScoreCast Raspberry Pi Image Configuration
# ==========================================

FILES_DIR="${STAGE_DIR}/00-install/files"

VERSION_SOURCE="${FILES_DIR}/scorecast-image-version"
INSTALLER_SOURCE="${FILES_DIR}/scorecast-image-install.sh"

VERSION_DEST="${ROOTFS_DIR}/etc/scorecast-image-version"
INSTALLER_DEST="${ROOTFS_DIR}/tmp/scorecast-image-install.sh"

# ==========================================
# Copy ScoreCast version and installer
# ==========================================

if [[ ! -s "${VERSION_SOURCE}" ]]; then
    echo "ERROR: ScoreCast version file missing." >&2
    exit 1
fi

if [[ ! -s "${INSTALLER_SOURCE}" ]]; then
    echo "ERROR: ScoreCast installer missing." >&2
    exit 1
fi

install -m 0644 \
    "${VERSION_SOURCE}" \
    "${VERSION_DEST}"

install -m 0755 \
    "${INSTALLER_SOURCE}" \
    "${INSTALLER_DEST}"

echo "ScoreCast version:"
cat "${VERSION_DEST}"

# ==========================================
# Configure Wi-Fi country on first boot
# ==========================================

echo "Installing ScoreCast Wi-Fi country setup..."

install -d -m 0755 \
    "${ROOTFS_DIR}/usr/local/sbin"

cat > \
"${ROOTFS_DIR}/usr/local/sbin/scorecast-wifi-country-init" <<'EOF'
#!/bin/bash
set -euo pipefail

MARKER="/var/lib/scorecast/wifi-country-initialized"

if [[ -f "${MARKER}" ]]; then
    exit 0
fi

echo "Configuring ScoreCast Wi-Fi country: US"

# Use Raspberry Pi OS's official configuration utility.
raspi-config nonint do_wifi_country US

# Clear the Wi-Fi soft block.
rfkill unblock wifi

# Ensure NetworkManager does not retain a disabled state.
STATE_FILE="/var/lib/NetworkManager/NetworkManager.state"

if [[ -f "${STATE_FILE}" ]]; then
    sed -i \
        's/^WirelessEnabled=.*/WirelessEnabled=true/' \
        "${STATE_FILE}"
fi

install -d -m 0755 /var/lib/scorecast
touch "${MARKER}"

echo "ScoreCast Wi-Fi country setup complete."
EOF

chmod 0755 \
    "${ROOTFS_DIR}/usr/local/sbin/scorecast-wifi-country-init"

# ==========================================
# First-boot systemd service
# ==========================================

install -d -m 0755 \
    "${ROOTFS_DIR}/etc/systemd/system"

cat > \
"${ROOTFS_DIR}/etc/systemd/system/scorecast-wifi-country.service" <<'EOF'
[Unit]
Description=Configure ScoreCast Wi-Fi country
Before=NetworkManager.service scorecast.service
ConditionPathExists=!/var/lib/scorecast/wifi-country-initialized

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/scorecast-wifi-country-init
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Enable the service in the image without running systemctl
# against the build machine.

install -d -m 0755 \
    "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants"

ln -sfn \
    ../scorecast-wifi-country.service \
    "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/scorecast-wifi-country.service"

echo "ScoreCast first-boot Wi-Fi setup installed."
echo "Image stage configuration complete."
