#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PYTHON=${PYTHON:-python3}
"$PYTHON" "$HERE/build_linedrawer.py" >/dev/null
exec "$PYTHON" "$HERE/verify_linedrawer.py" --vice "${VICE:-/opt/homebrew/bin/x64sc}" "$@"
