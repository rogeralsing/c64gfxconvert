#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
sky_source="${1:-$PWD/../../c64demo/images/rimrunner-bg.mci}"
python3 tools/prepare-rimrunner-parallax.py \
    --world-captures "$PWD/build/research/rimrunner/extracted/captures" \
    --source-ram "$PWD/build/research/rimrunner/extracted/captures/raster-00/ram.bin" \
    --output "$PWD/build/rimrunner-parallax-data"
python3 tools/extract-rimrunner-levels.py \
    --ram "$PWD/build/research/rimrunner/extracted/captures/raster-00/ram.bin" \
    --output "$PWD/build/rimrunner-levels"
python3 tools/prepare-rimrunner-mci-sky.py \
    --source "$sky_source" \
    --output "$PWD/build/rimrunner-mci-sky"
exec "$HOME/.local/bin/kickass" src/parallax.asm \
    -odir "$PWD/build" -o "$PWD/build/parallax.prg" \
    -debugdump -debug -symbolfile -vicesymbols
