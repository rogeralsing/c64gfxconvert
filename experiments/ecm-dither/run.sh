#!/bin/sh
set -eu
ECM_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$ECM_ROOT/build.sh"
exec /opt/homebrew/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$ECM_ROOT/build/ecm-dither.prg"
