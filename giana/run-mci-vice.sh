#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build-mci.sh
exec "${VICE:-x64sc}" -pal -speed 100 +warp +autostart-warp \
    -VICIIborders 0 -sounddev dummy -autostartprgmode 1 \
    -autostart "$PWD/build/giana-mci-borders.prg"
