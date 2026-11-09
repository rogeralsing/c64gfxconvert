#!/bin/sh
set -eu
LINE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$LINE_ROOT"
mkdir -p build
exec rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm \
  -odir "$LINE_ROOT/build" -o "$LINE_ROOT/build/line.prg" \
  -debugdump -debug -symbolfile -vicesymbols
