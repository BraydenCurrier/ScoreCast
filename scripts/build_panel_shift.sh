#!/usr/bin/env bash
# Compile the LED-matrix column shift used by the ticker.
set -euo pipefail

ROOT="${1:-}"
if [[ -z "${ROOT}" ]]; then
    echo "usage: build_panel_shift.sh ROOT" >&2
    exit 2
fi

PYTHON="${PYTHON:-python3}"
INCLUDE="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
SUFFIX="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX") or ".so")')"
MATRIX="${SCORECAST_RGB_MATRIX_DIR:-/opt/rpi-rgb-led-matrix}"
SRC="${ROOT}/src/common/panel_shift.cpp"
OUT="${ROOT}/src/common/panel_shift${SUFFIX}"

if [[ ! -f "${MATRIX}/lib/framebuffer-internal.h" ]]; then
    echo "RGB matrix headers not found; skipping the panel scroll helper." >&2
    exit 0
fi

g++ -shared -fPIC -O3 -std=c++17 \
    -I"${INCLUDE}" \
    -I"${MATRIX}/include" \
    -I"${MATRIX}/lib" \
    "${SRC}" \
    -o "${OUT}"

echo "Built ${OUT}"
