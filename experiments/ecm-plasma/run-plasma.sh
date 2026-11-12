#!/bin/sh
set -eu
PLASMA_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$PLASMA_ROOT/build-plasma.sh"
exec /opt/homebrew/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$PLASMA_ROOT/build/ecm-plasma.prg"
