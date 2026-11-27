#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
output=${LIVE_BALLS_OUTPUT:-$root/../../build/four-phase-top-sprites-live}
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
cd "$root"
node build-assets.cjs "$output" "$@"

assembler=${KICKASS:-kickass}
if [ -z "${KICKASS:-}" ] && ! command -v "$assembler" >/dev/null 2>&1; then
    assembler="$HOME/.local/bin/kickass"
fi
exec "$assembler" live.asm -odir "$output" -o "$output/four-phase-live.prg" -symbolfile -vicesymbols ":assets=$output"
