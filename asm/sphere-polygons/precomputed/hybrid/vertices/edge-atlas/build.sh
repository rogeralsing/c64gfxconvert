#!/bin/sh
set -eu
EDGE_ATLAS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec rtk proxy node "$EDGE_ATLAS_ROOT/build.cjs"
