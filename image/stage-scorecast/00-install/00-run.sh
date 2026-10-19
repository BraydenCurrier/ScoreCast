
#!/bin/bash -e
set -euo pipefail

FILES_DIR="${STAGE_DIR}/00-install/files"

VERSION_SOURCE="${FILES_DIR}/scorecast-image-version"
INSTALLER_SOURCE="${FILES_DIR}/scorecast-image-install.sh"

VERSION_DEST="${ROOTFS_DIR}/etc/scorecast-image-version"
INSTALLER_DEST="${ROOTFS_DIR}/tmp/scorecast-image-install.sh"

if [[ ! -s "${VERSION_SOURCE}" ]]; then
    echo "ERROR: ScoreCast version file is missing." >&2
    exit 1
fi

if [[ ! -s "${INSTALLER_SOURCE}" ]]; then
    echo "ERROR: ScoreCast installer is missing." >&2
    exit 1
fi

install -m 0644 "${VERSION_SOURCE}" "${VERSION_DEST}"
install -m 0755 "${INSTALLER_SOURCE}" "${INSTALLER_DEST}"

echo "ScoreCast image version:"
cat "${VERSION_DEST}"

echo "ScoreCast installer copied into image."
