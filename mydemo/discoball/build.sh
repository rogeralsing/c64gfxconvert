#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
variant=${1:-hexagon}
shape=pentagon
case "$variant" in
    hexagon) shape=hexagon; set -- -define HEXAGON ;;
    golden) set -- -define GOLDEN_PENTAGON ;;
    baseline) set -- ;;
    *) echo "Usage: sh build.sh [hexagon|baseline|golden]" >&2; exit 2 ;;
esac
mkdir -p "build/$variant"
python3 model.py --shape "$shape" --output build
python3 background.py
python3 prepare_fade.py
python3 prepare_music.py
exec "${KICKASS:-kickass}" main.asm -odir "$PWD/build/$variant" \
    -o "$PWD/build/$variant/sprite-ball.prg" -symbolfile -vicesymbols "$@"
