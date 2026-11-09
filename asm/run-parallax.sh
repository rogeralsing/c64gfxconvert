#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build-parallax.sh "$@"
exec /opt/homebrew/bin/x64sc +saveres -pal -speed 100 \
    +warp +autostart-warp -autostartprgmode 1 \
    -autostart "$PWD/build/parallax.prg"
