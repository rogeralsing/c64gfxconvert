#!/bin/sh
set -eu
POLYGON_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$POLYGON_ROOT"
node generate-assets.cjs
mkdir -p build
exec /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$POLYGON_ROOT/build" -o "$POLYGON_ROOT/build/polygon-spheres.prg" \
  -debugdump -debug -symbolfile -vicesymbols
