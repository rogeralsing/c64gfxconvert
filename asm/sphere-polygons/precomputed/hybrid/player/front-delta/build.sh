#!/bin/sh
set -eu
FRONT_DELTA_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec rtk proxy node "$FRONT_DELTA_ROOT/build.cjs"
