#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}

"$PYTHON" "$HERE/build-effects-assets.py"
"$PYTHON" "$HERE/build-effects-player.py"
