"""Run equal-budget evolutionary, random-search and loss-ablation experiments."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
from importlib.metadata import version
import json
import platform
import sys
import time
from pathlib import Path

import soundfile as sf

from fit import fit_target, prepare_target, save_result

HERE = Path(__file__).resolve().parent


def run_job(job: dict) -> dict:
    reference = Path(job["reference"])
    audio, sample_rate = sf.read(reference)
    target = prepare_target(audio, sample_rate, sample_rate)
    result = fit_target(target, sample_rate, job["kind"], seed=job["seed"],
                        budget=job["budget"], loss_mode=job["loss_mode"],
                        search_mode=job["search_mode"], note_hz=job["note_hz"])
    result["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    save_result(result, job["output"], target)
    return {key: result[key] for key in ("kind", "seed", "search_mode", "loss_mode", "evaluations", "seconds", "initial_scores", "best_scores")} | {"output": job["output"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/sweep")
    parser.add_argument("--budget", type=int, default=600)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--kinds", nargs="+", choices=["kick", "snare", "guitar"], default=["kick", "snare", "guitar"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE / "assets/manifest.json").read_text())
    targets = {item["id"]: item for item in manifest["samples"] if item["role"] == "fit"}
    jobs = []
    for kind in args.kinds:
        for seed in args.seeds:
            for search_mode, loss_mode in [("cmaes", "spectral"), ("random", "spectral"), ("cmaes", "mse")]:
                jobs.append({"kind": kind, "seed": seed, "search_mode": search_mode,
                             "loss_mode": loss_mode, "budget": args.budget,
                             "note_hz": targets[kind]["root_hz"] or 110.0,
                             "reference": str((HERE / "assets" / targets[kind]["file"]).resolve()),
                             "output": str((args.out / f"{kind}-{search_mode}-{loss_mode}-seed{seed}").resolve())})
    source_hashes = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                     for name in ("sid_render.py", "fit.py", "run_matrix.py", "requirements.txt")}
    (args.out / "plan.json").write_text(json.dumps({"jobs": jobs, "python": sys.version, "platform": platform.platform(),
                    "source_sha256": source_hashes,
                    "packages": {name: version(name) for name in ("pyresidfp", "numpy", "scipy", "cma", "soundfile")}}, indent=2) + "\n")
    snapshot = args.out / "source-snapshot"
    snapshot.mkdir(exist_ok=True)
    for name in source_hashes:
        (snapshot / name).write_bytes((HERE / name).read_bytes())
    started = time.perf_counter()
    summaries = []
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_job, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                summary = future.result()
                summaries.append(summary)
                print(json.dumps({"done": len(summaries), "total": len(jobs),
                                  "kind": summary["kind"], "seed": summary["seed"],
                                  "method": summary["search_mode"], "objective": summary["loss_mode"],
                                  "spectral": round(summary["best_scores"]["spectral"], 5),
                                  "seconds": round(summary["seconds"], 2)}), flush=True)
            except Exception as error:
                failures.append({"job": job, "error": repr(error)})
                print(json.dumps({"failed": job, "error": repr(error)}), flush=True)
            (args.out / "summary.json").write_text(json.dumps({"complete": len(summaries), "planned": len(jobs),
                    "elapsed_seconds": time.perf_counter() - started, "runs": summaries, "failures": failures}, indent=2) + "\n")
    if failures:
        raise SystemExit(f"{len(failures)} experiment jobs failed")


if __name__ == "__main__":
    main()
