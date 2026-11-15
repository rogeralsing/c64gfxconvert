#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
python3 tools/prepare-scene.py
python3 tools/prepare-level2.py
python3 tools/prepare-sprites.py
python3 tools/prepare-sprites.py --level 2
python3 tools/prepare-tv-highlight.py
python3 tools/prepare-tv-corners.py
python3 tools/prepare-music.py
exec "${KICKASS:-kickass}" main.asm -odir "$PWD/build" \
    -o "$PWD/build/giana.prg" -symbolfile -vicesymbols
