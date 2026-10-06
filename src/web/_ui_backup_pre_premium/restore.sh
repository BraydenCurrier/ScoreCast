#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../../.." && pwd)"
cp "$DIR/app.css" "$ROOT/src/web/static/app.css"
cp "$DIR/app.py" "$ROOT/src/web/app.py"
echo "Restored the previous dashboard UI into $ROOT/src/web"
echo "To put it on the live board:"
echo "  sudo rsync -a $ROOT/src/web/app.py /opt/scorecast/current/src/web/app.py"
echo "  sudo rsync -a $ROOT/src/web/static/app.css /opt/scorecast/current/src/web/static/app.css"
echo "  sudo systemctl restart scorecast"
