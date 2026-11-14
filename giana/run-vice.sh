#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec "${VICE:-x64sc}" -pal -sidenginemodel 256 -residsamp 2 -sound -autostartprgmode 1 \
    -autostart "$PWD/build/giana.prg"
