#!/usr/bin/env bash
set -euo pipefail

use_vertical_sine=false
if [[ $# -gt 0 && ${!#} == --y-sine ]]; then
    use_vertical_sine=true
    set -- "${@:1:$(( $# - 1 ))}"
fi

if [[ $# -lt 1 || $# -gt 10 ]]; then
    echo "Usage: bash build-four-line-scroll.sh <output-directory> [columns=64] [rows=16] [record|track|ribbon] [none|rows|columns|both|checker] [row-colors.bin] [step=1.5] [fields-per-step=4] [split-plan.json] [active-rows] [--y-sine]" >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
bitmap_args=("$1" "${2:-64}" "${3:-16}" "${4:-ribbon}" "${5:-none}")
if [[ -n ${9:-} ]]; then
    bitmap_args+=(--split-plan "$9")
fi
if [[ -n ${10:-} ]]; then
    bitmap_args+=(--active-rows "${10}")
fi
node "$script_dir/generate-four-line-bitmap.cjs" "${bitmap_args[@]}" --scroll "${@:6:1}"
out="$(cd -- "$1" && pwd)"
scroll_args=(--step "${7:-1.5}" --fields-per-step "${8:-4}")
if [[ $use_vertical_sine == true ]]; then
    scroll_args+=(--y-sine)
fi
node "$script_dir/generate-four-line-scroll.cjs" "$out" "$out/row-colors.bin" "${scroll_args[@]}"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
cp -- "$script_dir/four-line-scroll-player.asm" "$out/four-line-scroll-generated.asm" "$work/"
"${KICKASS:-kickass}" "$work/four-line-scroll-player.asm" \
    ":bitmapA=$out/phase-a/bitmap.bin" ":bitmapB=$out/phase-b/bitmap.bin" \
    ":rowColors=$out/row-colors-lz.bin" \
    -odir "$out" -o "$out/wave-four-line-scroll.prg"
