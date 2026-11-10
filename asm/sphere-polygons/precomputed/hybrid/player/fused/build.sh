#!/bin/sh
set -eu
FUSED_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$FUSED_ROOT"
test -f ../build/assets/checker-64.hc64
test -f ../build/assets/font.bin
mkdir -p build
exec "${KICKASS:-kickass}" main.asm \
  -odir "$FUSED_ROOT/build" -o "$FUSED_ROOT/build/player.prg" \
  -debugdump -debug -symbolfile -vicesymbols
