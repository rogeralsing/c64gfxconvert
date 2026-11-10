"""Fit a guitar patch without claiming the SID's shared filter as a resource."""
from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf

from fit import FAMILIES, fit_target, prepare_target, save_result

HERE = Path(__file__).resolve().parent


def main() -> None:
    manifest = json.loads((HERE / "assets/manifest.json").read_text())
    sample = next(item for item in manifest["samples"] if item["id"] == "guitar")
    audio, sample_rate = sf.read(HERE / "assets" / sample["file"])
    target = prepare_target(audio, sample_rate, sample_rate)
    # This process-local experimental override leaves the main sweep unchanged.
    FAMILIES["guitar"] = [("pulse", "off"), ("saw", "off"), ("triangle", "off")]
    result = fit_target(target, sample_rate, "guitar", seed=1, budget=600,
                        loss_mode="spectral", search_mode="cmaes", note_hz=sample["root_hz"])
    result["experiment"] = "One SID voice, filter bypassed in all candidate families"
    result["families"] = FAMILIES["guitar"]
    result["scope"] = "One seed and equal per-run budget; exploratory filter-resource ablation, not a three-seed superiority claim."
    output = HERE / "results/fresh-hybrid-checks/filter-free-guitar"
    save_result(result, output, target)
    print(json.dumps({"output": str(output), "best_scores": result["best_scores"], "seconds": result["seconds"]}))


if __name__ == "__main__":
    main()
