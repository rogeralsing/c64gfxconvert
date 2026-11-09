#!/bin/sh
set -eu
VERTEX_PLAYER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$VERTEX_PLAYER_ROOT"
mkdir -p build
exec rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$VERTEX_PLAYER_ROOT/build" -o "$VERTEX_PLAYER_ROOT/build/player.prg" \
  -debugdump -debug -symbolfile -vicesymbols
