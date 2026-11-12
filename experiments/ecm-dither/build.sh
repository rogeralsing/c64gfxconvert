#!/bin/sh
set -eu
ECM_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ECM_ROOT"
python3 generate.py
exec /Users/rogerjohansson/.local/bin/kickass demo.asm \
  -odir "$ECM_ROOT/build" -o "$ECM_ROOT/build/ecm-dither.prg" \
  -debugdump -debug -symbolfile -vicesymbols
