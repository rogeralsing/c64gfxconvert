#!/bin/sh
set -eu
SPHERE_EXPERIMENT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$SPHERE_EXPERIMENT"
python3 optimization/common/build_variant.py optimization/shared-edge-cache
exec /opt/homebrew/Cellar/vice/3.10/bin/x64sc -default +saveres -pal -speed 100 \
  +warp +autostart-warp +confirmonexit -sounddev dummy \
  -autostartprgmode 1 -autostart "$SPHERE_EXPERIMENT/optimization/shared-edge-cache/build/variant.prg"
