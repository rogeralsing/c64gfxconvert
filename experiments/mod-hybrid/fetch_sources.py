"""Fetch selected MOD sources and verify their recorded identities."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request


HERE = Path(__file__).resolve().parent
SONGS = ("stardust-memories", "hyperbased", "4mats-madness")
CANDIDATES = ("global-trash-3", "madness-took-me", "rink-a-dink", "elysium",
              "global-trash", "mobyle", "livin-insanity", "elektrik-funk",
              "desert-dream-1", "guitar-slinger", "klisje-paa-klisje",
              "physical-presence", "condom-corruption")


def fetch_sources(directory: Path = HERE / "sources", songs: tuple[str, ...] = SONGS) -> list[dict]:
    results = []
    for name in songs:
        if name not in SONGS + CANDIDATES:
            raise ValueError(f"Unknown MOD source: {name}")
        receipt = json.loads((directory / f"{name}.source.json").read_text())
        target = directory / f"{name}.mod"
        expected_size = int(receipt["bytes"])
        if target.exists():
            data = target.read_bytes()
            action = "verified existing"
        else:
            url = receipt.get("download_url") or receipt["source_url"]
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read(expected_size + 1)
            action = "downloaded"
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or digest != receipt["sha256"]:
            raise ValueError(f"Source identity mismatch for {target}; file was not overwritten")
        if not target.exists():
            target.write_bytes(data)
        results.append({"source": name, "action": action, "bytes": len(data), "sha256": digest})
    return results


if __name__ == "__main__":
    print(json.dumps(fetch_sources(), indent=2))
