"""Audit final experiment artifacts against the declared research scope."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import py_compile

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent


def read(path: str | Path) -> dict:
    return json.loads((HERE / path).read_text())


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value and "://" not in value and not value.startswith("#"):
                self.paths.append(value)


def main() -> None:
    checks = []

    def require(condition: bool, message: str) -> None:
        checks.append({"contract": message, "pass": bool(condition)})

    for path in HERE.glob("*.py"):
        py_compile.compile(str(path), doraise=True)
    require(True, "All lab Python entry points compile")
    assets = read("assets/manifest.json")["samples"]
    for item in assets:
        path = HERE / "assets" / item["file"]
        samples, rate = sf.read(path)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], f"{item['id']} matches its reference digest")
        require(rate == 22050 and samples.ndim == 1 and len(samples) == 17640 and np.isfinite(samples).all(), f"{item['id']} is finite 0.8-second mono PCM at 22050 Hz")
    require(len({item["original_sha256"] for item in assets}) == 4, "Four independent original audio files, including the guitar holdout")
    plan = read("results/fresh-sweep/plan.json")
    summary = read("results/fresh-sweep/summary.json")
    require(summary["complete"] == summary["planned"] == len(plan["jobs"]) == 27 and not summary["failures"], "All 27 corrected-renderer experiment jobs completed")
    for name, digest in plan["source_sha256"].items():
        require(hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest, f"Current {name} matches the final matrix source")
    runs = {}
    for job in plan["jobs"]:
        directory = Path(job["output"])
        result = json.loads((directory / "results.json").read_text())
        key = (job["kind"], job["seed"], job["search_mode"], job["loss_mode"])
        runs[key] = result
        require(result["evaluations"] == result["budget"] == len(result["history"]) == 600, f"{directory.name} spent exactly 600 candidate renders")
        target, rate = sf.read(directory / "target.wav")
        fitted, fitted_rate = sf.read(directory / "best.wav")
        require(rate == fitted_rate == result["sample_rate"] and target.shape == fitted.shape and np.isfinite(fitted).all(), f"{directory.name} exports matching finite target/fitted audio")
    for kind in ("kick", "snare", "guitar"):
        for seed in (1, 2, 3):
            cases = [runs[(kind, seed, method, loss)] for method, loss in (("cmaes", "spectral"), ("random", "spectral"), ("cmaes", "mse"))]
            prefixes = [[entry["patch"] for entry in run["history"][:150]] for run in cases]
            require(prefixes[0] == prefixes[1] == prefixes[2], f"{kind}/seed{seed} uses identical 150-program starting candidates")
    selection = read("results/finalists/selection.json")
    require(set(selection["kinds"]) == {"kick", "snare", "guitar"}, "All three instruments have selected finalists")
    for kind, group in selection["kinds"].items():
        winner = group["winner"]
        means = [float(np.mean([score["spectral"] for score in candidate["repeat_scores"]])) for candidate in group["candidates"]]
        require(all(len(candidate["repeat_scores"]) == 5 for candidate in group["candidates"]), f"Every distinct {kind} finalist was rendered five times")
        require(abs(winner["spectral_mean"] - min(means)) < 1e-10, f"{kind} finalist selected by repeated mean score")
        require(read(f"results/finalists/{kind}/patch.json") == winner["patch"], f"{kind} exported patch matches the selected finalist")
        receipt = read(f"results/vice-{kind}/receipt.json")
        require(receipt["trace"]["register_sequence_matches"] and receipt["trace"]["max_timing_error_cycles"] == 0 and receipt["trace"]["timing_mismatches"] == 0, f"{kind} PRG matches all native register writes and cycle timestamps in VICE")
        samples, rate = sf.read(HERE / f"results/vice-{kind}/vice.wav")
        require(len(samples) > 0 and np.isfinite(samples).all() and np.max(np.abs(samples)) > 0.001, f"{kind} VICE playback produced actual non-silent PCM")
        instrument, instrument_rate = sf.read(HERE / f"results/vice-{kind}/vice-instrument.wav")
        require(instrument_rate == rate and len(instrument) == round(receipt["duration_s"] * rate)
                and np.isfinite(instrument).all() and np.max(np.abs(instrument)) > 0.001,
                f"{kind} VICE instrument window is complete and non-silent independently of boot clicks")
        require(abs(receipt["audio"]["alignment_delta_from_timeline_samples"]) <= round(rate * 0.02),
                f"{kind} audio comparison is anchored to register timing within 20 ms")
    robust = read("results/robustness/robustness.json")
    require(set(robust["kinds"]) == {"kick", "snare", "guitar"}, "All three instruments have robustness measurements")
    for kind, result in robust["kinds"].items():
        require(len(result["repeatability"]["scores"]) == 10, f"{kind} has ten fresh-state repeat measurements")
        require(set(result["control_rates"]) == {"50", "100", "200", "400"} and set(result["models"]) == {"6581", "8580"}, f"{kind} checked at four curve rates and both chip models")
        require(set(result["histories"]) == {"same", "different"}, f"{kind} checked after same and different preceding notes")
    holdout = robust["guitar_holdout"]
    require(holdout["same_patch_as_training"] and holdout["reference_is_independent_recording"] and holdout["no_retraining"], "Independent guitar note checked without retraining")
    waveforms = read("results/waveform-checks/waveform-checks.json")
    conditions = waveforms["conditions"]
    require({(row["model"], row["mask"]) for row in conditions.values()} == {(model, mask) for model in ("6581", "8580") for mask in (0x10, 0x20, 0x40, 0x30, 0x50, 0x60, 0x70)}, "Seven waveform masks measured on each of two chip models")
    for name, row in conditions.items():
        require(len(row["scores"]) == 5 and np.isfinite([score["spectral"] for score in row["scores"]]).all(), f"Waveform {name} has five finite score measurements")
        samples, rate = sf.read(HERE / "results/waveform-checks" / row["raw_audio"])
        require(rate == 22050 and len(samples) > 0 and np.isfinite(samples).all(), f"Waveform {name} raw PCM decodes")
    layered = read("results/fresh-layered-snare/summary.json")
    require(set(layered["runs"]) == {"cmaes", "random"} and all(run["evaluations"] == 600 and len(run["repeat_scores"]) == 5 for run in layered["runs"].values()), "Two-voice snare has two equal-budget searches and repeated measurements")
    filter_free = read("results/fresh-hybrid-checks/filter-free-guitar/results.json")
    require(filter_free["evaluations"] == 600 and filter_free["best_patch"]["filter_mode"] == "off", "Filter-free guitar search completed its budget without enabling the shared filter")
    numerical = read("results/search-checks.json")
    require(numerical["status"] == "pass" and not numerical["failures"], "Independent metric controls and synthetic loop recovery passed")
    require(all(item["within_one_hz"] for item in read("results/render-contract.json")["results"]), "PAL oscillator frequency independently checked against the SID register formula")
    parser = Links()
    parser.feed((HERE / "listen.html").read_text())
    require(all((HERE / path).is_file() for path in parser.paths), "Every listening-page local audio/artifact link resolves")
    provenance = read("results/provenance.json")
    require(all(hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest for name, digest in provenance["current_source_sha256"].items()), "Final source files match the provenance receipt")
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "status": "pass" if all(check["pass"] for check in checks) else "fail",
              "scope": "Artifact integrity, equal search budgets, repeated score selection, emulator execution, and declared robustness conditions. Not a human listening test or real SID hardware validation."}
    (HERE / "results/audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": len(checks), "failures": [check for check in checks if not check["pass"]]}))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
