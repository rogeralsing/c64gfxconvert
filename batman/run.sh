#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec "${VICE:-x64sc}" -default +saveres -pal -speed 100 +warp +autostart-warp \
    -VICIIborders 0 -sounddev dummy -VICIIfilter 0 \
    -VICIIextpal -VICIIpalette "$PWD/assets/peptoette-a.vpl" \
    -VICIIsaturation 1000 -VICIIcontrast 1000 -VICIIbrightness 1000 -VICIIgamma 1000 \
    -autostartprgmode 1 -autostart "$PWD/build/batman.prg"
