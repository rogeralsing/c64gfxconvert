#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec "${VICE:-x64sc}" -pal -autostartprgmode 1 \
    -autostart "$PWD/build/giana.prg"
