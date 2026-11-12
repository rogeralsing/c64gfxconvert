#!/bin/sh
set -eu
VIEWPORT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$VIEWPORT_ROOT/build-viewports.sh"
exec /opt/homebrew/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$VIEWPORT_ROOT/build/ecm-viewports.prg"
