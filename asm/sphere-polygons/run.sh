#!/bin/sh
set -eu
POLYGON_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$POLYGON_ROOT/build.sh"
exec /opt/homebrew/Cellar/vice/3.10/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$POLYGON_ROOT/build/polygon-spheres.prg"
