#!/bin/sh
set -eu
FAST_VERTEX_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec rtk proxy node "$FAST_VERTEX_ROOT/build-fast.cjs"
