#!/bin/sh
set -eu
VERTEX_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
rtk proxy node "$VERTEX_ROOT/generate.cjs"
rtk proxy sh "$VERTEX_ROOT/span-atlas/build.sh"
exec rtk proxy "${VICE:-x64sc}" -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$VERTEX_ROOT/span-atlas/build/player.prg"
