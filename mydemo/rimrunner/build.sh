#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build/rimrunner-parallax-data
sky_source="${1:-$PWD/assets/rimrunner-bg.mci}"
road_source="${2:-$PWD/assets/rimrunner-road2.mci}"
cp assets/mounted/mounted-unique.bin assets/mounted/mounted-frame-map.bin \
    assets/mounted/mounted-offsets.bin build/rimrunner-parallax-data/
python3 tools/prepare-rimrunner-mci-composite.py \
    --background "$sky_source" \
    --road "$road_source" \
    --output "$PWD/build/rimrunner-mci-composite"
exec "${KICKASS:-$HOME/.local/bin/kickass}" src/parallax.asm \
    -odir "$PWD/build" -o "$PWD/build/parallax.prg" \
    -debugdump -debug -symbolfile -vicesymbols
