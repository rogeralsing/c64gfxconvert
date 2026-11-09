#!/bin/sh
set -eu
PLAYER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
rtk proxy node "$PLAYER_ROOT/prepare-assets.cjs"
rtk proxy sh "$PLAYER_ROOT/unrolled/build.sh"
exec rtk proxy "${VICE:-x64sc}" -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$PLAYER_ROOT/unrolled/build/player.prg"
