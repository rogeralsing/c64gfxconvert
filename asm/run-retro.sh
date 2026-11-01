#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
./build.sh
exec "/Applications/Retro Debugger.app/Contents/MacOS/Retro Debugger" \
    -pass -c64 -wait 1000 \
    -prg "$PWD/build/hello-raster.prg" \
    -debuginfo "$PWD/build/hello-raster.dbg" -autojmp -unpause
