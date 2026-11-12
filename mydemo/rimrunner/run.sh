#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh "$@"
exec "${VICE:-/opt/homebrew/bin/x64sc}" -default +saveres -pal -speed 100 \
    +warp +autostart-warp -autostartprgmode 1 \
    -autostart "$PWD/build/parallax.prg"
