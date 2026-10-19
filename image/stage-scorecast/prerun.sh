
#!/bin/bash -e

# Start with the Raspberry Pi OS filesystem
# created by the previous build stage.

if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
