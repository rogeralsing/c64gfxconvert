#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
exec /Users/rogerjohansson/.local/bin/kickass src/main.asm \
    -odir "$PWD/build" -o "$PWD/build/hello-raster.prg" \
    -debugdump -debug -symbolfile -vicesymbols \
    -asminfo 'files|errors' -asminfofile "$PWD/build/hello-raster.info"
