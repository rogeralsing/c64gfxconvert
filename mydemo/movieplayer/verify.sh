#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}

"$HERE/build.sh"
exec "$PYTHON" "$HERE/verify-effects-player.py" "$@"
