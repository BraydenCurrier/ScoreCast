
#!/bin/bash -e

# ScoreCast Raspberry Pi Image Installer
# Runs inside the Raspberry Pi OS image during build.

echo "======================================"
echo " Installing ScoreCast into Pi OS"
echo "======================================"

# Get the ScoreCast version selected by
# the GitHub Actions build.
SCORECAST_VERSION="$(
    cat /etc/scorecast-image-version
)"

echo "Installing ScoreCast ${SCORECAST_VERSION}"

# Download the exact version of ScoreCast.
git clone \
    --branch "${SCORECAST_VERSION}" \
    --depth 1 \
    https://github.com/BraydenCurrier/ScoreCast.git \
    /tmp/scorecast-source

# Run ScoreCast's installer in image-build mode.
export SCORECAST_VERSION
export SCORECAST_IMAGE_BUILD=1

bash /tmp/scorecast-source/scripts/install.sh

# Remove temporary installation files.
rm -rf /tmp/scorecast-source

echo "ScoreCast installation complete."
