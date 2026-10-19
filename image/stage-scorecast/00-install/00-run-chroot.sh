
#!/bin/bash -e
set -euo pipefail

VERSION_FILE="/etc/scorecast-image-version"
INSTALLER="/tmp/scorecast-image-install.sh"

if [[ ! -s "${VERSION_FILE}" ]]; then
    echo "ERROR: Missing ScoreCast version." >&2
    exit 1
fi

if [[ ! -f "${INSTALLER}" ]]; then
    echo "ERROR: Missing ScoreCast installer." >&2
    exit 1
fi

export SCORECAST_VERSION="$(cat "${VERSION_FILE}")"
export SCORECAST_IMAGE_BUILD=1

echo "Installing ScoreCast: ${SCORECAST_VERSION}"

bash "${INSTALLER}"

rm -f "${INSTALLER}"

echo "ScoreCast installation complete."
