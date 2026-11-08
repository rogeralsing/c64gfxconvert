#!/bin/sh
set -eu
SPHERE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SPHERE_ROOT"
node generate-assets.cjs
mkdir -p build
exec /Users/rogerjohansson/.local/bin/kickass sphere.asm \
  -odir "$SPHERE_ROOT/build" -o "$SPHERE_ROOT/build/sphere.prg" \
  -debugdump -debug -symbolfile -vicesymbols
