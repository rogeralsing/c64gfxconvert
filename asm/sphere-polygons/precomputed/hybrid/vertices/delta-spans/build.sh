#!/bin/sh
set -eu
DELTA_SPANS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec rtk proxy node "$DELTA_SPANS_ROOT/build.cjs"
