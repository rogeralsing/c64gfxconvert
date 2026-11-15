#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec "${VICE:-x64sc}" -pal -sidenginemodel 256 -residsamp 2 -sound -drive8truedrive \
    -autostart "$PWD/build/giana.d64"
