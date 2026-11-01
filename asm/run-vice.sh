#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec /opt/homebrew/bin/x64sc -pal -autostartprgmode 1 \
    -autostart "$PWD/build/hello-raster.prg"
