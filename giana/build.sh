#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
python3 tools/prepare-scene.py
exec "${KICKASS:-kickass}" main.asm -odir "$PWD/build" \
    -o "$PWD/build/giana.prg" -symbolfile -vicesymbols
