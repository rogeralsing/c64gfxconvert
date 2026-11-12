#!/bin/sh
set -eu
ECM_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ECM_ROOT"
python3 generate-metaballs.py
exec /Users/rogerjohansson/.local/bin/kickass metaballs.asm \
  -odir "$ECM_ROOT/build/metaballs" -o "$ECM_ROOT/build/metaballs/metaballs.prg" \
  -debugdump -debug -symbolfile -vicesymbols
