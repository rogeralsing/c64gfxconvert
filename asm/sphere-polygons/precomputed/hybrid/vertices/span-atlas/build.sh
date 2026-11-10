#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec rtk proxy node build.cjs
