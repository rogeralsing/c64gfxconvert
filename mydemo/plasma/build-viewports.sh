#!/bin/sh
set -eu
VIEWPORT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$VIEWPORT_ROOT"
python3 generate-viewports.py
exec /Users/rogerjohansson/.local/bin/kickass viewports.asm \
  -odir "$VIEWPORT_ROOT/build" -o "$VIEWPORT_ROOT/build/ecm-viewports.prg" \
  -debugdump -debug -symbolfile -vicesymbols
