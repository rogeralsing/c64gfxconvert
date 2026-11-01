#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
disk="${1:-$PWD/butterfly.d64}"
if [ "$#" -gt 0 ]; then shift; fi
exec /opt/homebrew/bin/x64sc -pal -speed 100 +warp +reu +refreshonbreak \
    +drive8truedrive -trapdevice8 -sounddev dummy \
    -autostart "$disk" "$@"
