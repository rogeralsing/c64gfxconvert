#!/usr/bin/env python3
"""Build the pinned Spindle Spin disk tool locally, without system installs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


PART = Path(__file__).resolve().parents[1]
VENDOR = PART / "vendor" / "spindle"
BUILD = PART / "build" / "tools"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> Path:
    provenance = json.loads((VENDOR / "UPSTREAM.json").read_text())
    for name, expected in provenance["vendored_sha256"].items():
        if sha256((VENDOR / name).read_bytes()) != expected:
            raise ValueError(f"Vendored Spindle source changed: {name}")
    BUILD.mkdir(parents=True, exist_ok=True)
    executable = BUILD / "spin"
    compiler = os.environ.get("CC", "cc")
    source = VENDOR / "src"
    command = [compiler, "-O3", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-Wall",
               "-o", str(executable),
               *(str(source / name) for name in ("spin.c", "pack.c", "disk.c", "util.c"))]
    subprocess.run(command, check=True)
    version = subprocess.run([str(executable), "-V"], check=True, capture_output=True, text=True)
    reported_version = (version.stdout + version.stderr).strip()
    if reported_version != "Spindle 3.1 by lft, https://linusakesson.net/software/spindle/":
        raise ValueError(f"Unexpected Spin version: {reported_version}")
    receipt = {"format": "giana-local-spindle-tool-v1", "version": reported_version,
               "source_archive_sha256": provenance["archive_sha256"],
               "generated_tables_sha256": provenance["generated_tables"]["sha256"],
               "executable": str(executable.relative_to(PART)),
               "executable_sha256": sha256(executable.read_bytes()), "command": command}
    (BUILD / "spindle-tool.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return executable


if __name__ == "__main__":
    print(build())
