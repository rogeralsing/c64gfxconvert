#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VICE=${VICE:-/opt/homebrew/bin/x64sc}

"$HERE/build.sh"
exec "$VICE" -default +saveres -pal -speed 100 +warp +autostart-warp \
    -autostartprgmode 1 -VICIIfilter 0 -VICIIextpal \
    -VICIIpalette "$HERE/../../palettes/colodore.vpl" -VICIIsaturation 1000 \
    -VICIIcontrast 1000 -VICIIbrightness 1000 -VICIIgamma 1000 \
    -autostart "$HERE/build/player.prg" "$@"
