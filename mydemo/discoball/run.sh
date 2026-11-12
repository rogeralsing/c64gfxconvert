#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
variant=hexagon
case "${1:-}" in hexagon|baseline|golden) variant=$1; shift ;; esac
sh build.sh "$variant"
exec "${VICE:-x64sc}" -pal +saveres -speed 100 +warp +autostart-warp \
    -sound -sidmodel 1 -autostartprgmode 1 -autostart "$PWD/build/$variant/sprite-ball.prg" "$@"
