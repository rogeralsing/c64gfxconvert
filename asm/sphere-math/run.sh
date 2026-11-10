#!/bin/sh
set -eu
SPHERE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$SPHERE_ROOT/build.sh"
exec /opt/homebrew/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$SPHERE_ROOT/build/sphere.prg"
