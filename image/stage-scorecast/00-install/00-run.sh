
#!/bin/bash -e

# Copy the ScoreCast release version
# into the Raspberry Pi filesystem.

VERSION_SOURCE="${STAGE_DIR}/00-install/files/scorecast-image-version"

VERSION_DEST="${ROOTFS_DIR}/etc/scorecast-image-version"

# Make sure the version file exists.
if [ ! -f "${VERSION_SOURCE}" ]; then
    echo "ERROR: ScoreCast version file not found!"
    exit 1
fi

# Copy the version into the image.
install -m 0644 \
    "${VERSION_SOURCE}" \
    "${VERSION_DEST}"

echo "ScoreCast image version:"
cat "${VERSION_DEST}"
