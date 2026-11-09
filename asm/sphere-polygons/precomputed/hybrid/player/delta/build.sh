#!/bin/sh
set -eu
DELTA_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DELTA_ROOT"
mkdir -p build
exec rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$DELTA_ROOT/build" -o "$DELTA_ROOT/build/player.prg" \
  -debugdump -debug -symbolfile -vicesymbols
