#!/bin/sh
set -eu
PLASMA_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PLASMA_ROOT"
python3 generate-plasma.py
exec /Users/rogerjohansson/.local/bin/kickass plasma.asm \
  -odir "$PLASMA_ROOT/build" -o "$PLASMA_ROOT/build/ecm-plasma.prg" \
  -debugdump -debug -symbolfile -vicesymbols
