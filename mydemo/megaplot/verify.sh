#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec "${PYTHON:-python3}" "$HERE/verify_megaplot.py" --rebuild --vice "${VICE:-/opt/homebrew/bin/x64sc}" "$@"
