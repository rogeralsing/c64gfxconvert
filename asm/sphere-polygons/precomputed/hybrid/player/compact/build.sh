#!/bin/sh
set -eu
COMPACT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$COMPACT_ROOT"
mkdir -p build
exec rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$COMPACT_ROOT/build" -o "$COMPACT_ROOT/build/player.prg" \
  -debugdump -debug -symbolfile -vicesymbols
