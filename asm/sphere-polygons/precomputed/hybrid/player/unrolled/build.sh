#!/bin/sh
set -eu
PLAYER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PLAYER_DIR"
rtk proxy node generate.cjs
exec rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$PLAYER_DIR/build" -o "$PLAYER_DIR/build/player.prg" \
  -debugdump -debug -symbolfile -vicesymbols
