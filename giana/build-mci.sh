#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p build
python3 ../mci-viewer/build-prg.py assets/giana-man.mci \
    --assembler "${KICKASS:-kickass}" --force --output "$PWD/build/giana-mci.prg"
exec python3 ../mci-viewer/build-prg.py assets/giana-man.mci \
    --assembler "${KICKASS:-kickass}" --force --borders --output "$PWD/build/giana-mci-borders.prg"
