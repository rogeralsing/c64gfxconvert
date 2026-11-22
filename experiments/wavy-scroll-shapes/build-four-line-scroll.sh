#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 7 ]]; then
    echo "Usage: bash build-four-line-scroll.sh <output-directory> [columns=64] [rows=16] [record|track|ribbon] [none|rows|columns|both|checker] [row-colors.bin] [step=1.5]" >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
node "$script_dir/generate-four-line-bitmap.cjs" "$1" "${2:-64}" "${3:-16}" "${4:-ribbon}" "${5:-checker}" --scroll "${@:6:1}"
out="$(cd -- "$1" && pwd)"
node "$script_dir/generate-four-line-scroll.cjs" "$out" "$out/row-colors.bin" --step "${7:-1.5}"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
cp -- "$script_dir/four-line-scroll-player.asm" "$out/four-line-scroll-generated.asm" "$work/"
"${KICKASS:-kickass}" "$work/four-line-scroll-player.asm" \
    ":bitmapA=$out/phase-a/bitmap.bin" ":bitmapB=$out/phase-b/bitmap.bin" \
    ":rowColors=$out/row-colors-lz.bin" \
    -odir "$out" -o "$out/wave-four-line-scroll.prg"
