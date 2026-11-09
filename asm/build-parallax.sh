#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
sky_source="${1:-$PWD/../../c64demo/images/rimrunner-bg.mci}"
road_source="${2:-$PWD/../../c64demo/images/rimrunner-road2.mci}"
python3 tools/prepare-rimrunner-parallax.py \
    --world-captures "$PWD/build/research/rimrunner/extracted/captures" \
    --source-ram "$PWD/build/research/rimrunner/extracted/captures/raster-00/ram.bin" \
    --output "$PWD/build/rimrunner-parallax-data"
python3 tools/prepare-rimrunner-mci-composite.py \
    --background "$sky_source" \
    --road "$road_source" \
    --output "$PWD/build/rimrunner-mci-composite"
exec "$HOME/.local/bin/kickass" src/parallax.asm \
    -odir "$PWD/build" -o "$PWD/build/parallax.prg" \
    -debugdump -debug -symbolfile -vicesymbols
