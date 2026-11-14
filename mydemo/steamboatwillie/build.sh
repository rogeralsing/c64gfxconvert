#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${PYTHON:-}" ]; then
    player_python=$PYTHON
elif [ -x "$HERE/.venv/bin/python" ]; then
    player_python="$HERE/.venv/bin/python"
else
    player_python=python3
fi

exec "$player_python" "$HERE/build-player.py" "$@"
