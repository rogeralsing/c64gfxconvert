"""Capture current lab source, installed package versions, and asset digests."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import platform
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main() -> None:
    files = sorted(HERE.glob("*.py")) + [HERE / "requirements.txt", HERE / "reset-cases.json", HERE / "assets/prepare.py", HERE / "assets/manifest.json"]
    sources = {str(path.relative_to(HERE)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    manifest = json.loads((HERE / "assets/manifest.json").read_text())
    assets = []
    for item in manifest["samples"]:
        path = HERE / "assets" / item["file"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assets.append({"file": item["file"], "sha256": actual, "matches_manifest": actual == item["sha256"]})
    receipt = {"generated_utc": datetime.now(timezone.utc).isoformat(),
               "python": sys.version, "platform": platform.platform(),
               "packages": {name: version(name) for name in ("pyresidfp", "numpy", "scipy", "cma", "soundfile")},
               "current_source_sha256": sources, "assets": assets,
               "scope": "Current source snapshot. Individual experiment source snapshots distinguish the initial cached-reset renderer from any corrected renderer."}
    output = HERE / "results/provenance.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    if not all(item["matches_manifest"] for item in assets):
        raise SystemExit("A reference asset no longer matches its provenance manifest")
    print(output)


if __name__ == "__main__":
    main()
