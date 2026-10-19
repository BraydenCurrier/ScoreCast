
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


# Download ScoreCast and check out the requested
# release tag or exact commit.

REPO_URL="https://github.com/BraydenCurrier/ScoreCast.git"
SOURCE_DIR="/tmp/scorecast-source"

rm -rf "${SOURCE_DIR}"

git clone "${REPO_URL}" "${SOURCE_DIR}"

cd "${SOURCE_DIR}"

# Check that the requested version exists.
git rev-parse --verify "${SCORECAST_VERSION}^{commit}"

# Switch to the requested tag or commit.
git checkout --detach "${SCORECAST_VERSION}"

echo "Checked out ScoreCast version:"
git rev-parse HEAD


# Run ScoreCast's installer in image-build mode.
export SCORECAST_VERSION
export SCORECAST_IMAGE_BUILD=1

bash /tmp/scorecast-source/scripts/install.sh

# Remove temporary installation files.
rm -rf /tmp/scorecast-source

echo "ScoreCast installation complete."
