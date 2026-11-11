"""Build pinned full songs or the current candidate set using one playback profile."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import shutil

from contextual_banks import combine
from fetch_sources import CANDIDATES, fetch_sources
from pcm4_build import build
from pcm4_prepare import prepare
from vice_profile import PROFILE


HERE = Path(__file__).resolve().parent
EXPECTED = {
    "stardust-memories": "ee0b7514369a9e1d55a4523500d21c87d901a76b92a65c3d18b988b379e0e29b",
    "hyperbased": "0434f8171b94a1c6f44d9923b2143fc91b8688443061f5db3b49090297a4a980",
    "4mats-madness": "3961595a2efa07e0338f058dd7d56ae1006aac6210aed397c104e0884f590df6",
}


def set_gain(path: Path, value: float) -> None:
    arrangement = json.loads(path.read_text())
    arrangement["mixing"]["output_gain"] = value
    path.write_text(json.dumps(arrangement, separators=(",", ":")) + "\n")


def build_release(out: Path) -> dict:
    sources = fetch_sources()
    out = out.resolve()
    players = out / "players"
    players.mkdir(parents=True, exist_ok=True)
    records = []
    for name, expected in EXPECTED.items():
        folder = out / name
        source = HERE / "sources" / f"{name}.mod"
        if name == "4mats-madness":
            fallback, preferred = folder / "fallback", folder / "preferred"
            prepare(source, fallback, bank_scope="score")
            prepare(source, preferred, seconds=50, bank_scope="score")
            set_gain(preferred / "arrangement.json", 3.0)
            result = combine(fallback / "arrangement.json", preferred / "arrangement.json", folder / "contextual")
            if result["preferred_prefix_dac_mismatches"]:
                raise ValueError("Madness no longer preserves its preferred short score")
            arrangement = folder / "contextual/arrangement.json"
        else:
            prepare(source, folder)
            arrangement = folder / "arrangement.json"
            if name == "hyperbased":
                set_gain(arrangement, 3.0)
        built = build(arrangement, folder / "c64", score_codec="dictionary8")
        program = Path(built["program"])
        digest = hashlib.sha256(program.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Release program changed for {name}: {digest}; expected {expected}")
        target = players / f"{name}-full.prg"
        shutil.copyfile(program, target)
        records.append({"song": name, "program": target.relative_to(out).as_posix(),
                        "bytes": target.stat().st_size, "sha256": digest,
                        "duration_s": built["duration_s"], "ticks": built["ticks"],
                        "program_end": built["program_end"], "matches_verified_release": True})
        print(f"Verified {name}: {records[-1]['bytes']} bytes", flush=True)
    manifest = {"status": "all_release_programs_reproduced", "sources": sources,
                "programs": records, "playback_profile": dict(PROFILE),
                "scope": "Complete PRG hashes match the pinned release; playback uses PAL/8580 + digiboost. Historical PAL/6581 captures remain separate evidence. Generated build inputs contain local paths and are recreated on each checkout."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def build_candidate(name: str, out: Path, seconds: float, capture_audio: bool) -> dict:
    """Build one substantial passage, then verify its actual C64 output."""
    folder = out / name
    source = HERE / "sources" / f"{name}.mod"
    provenance = json.loads(source.with_suffix(".source.json").read_text())
    record = {"song": name, "title": provenance.get("title", name),
              "author": provenance.get("author"), "source_page": provenance["source_page"],
              "source_sha256": provenance["sha256"], "requested_seconds": seconds,
              "playback_profile": dict(PROFILE), "status": "building"}
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / "candidate.json"
    try:
        previous_record = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        previous_record = {}
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    try:
        prepared = prepare(source, folder, seconds=seconds, bank_scope="score", protracker_loops=True)
        arrangement_path = folder / "arrangement.json"
        if name == "guitar-slinger":
            # Quiet guitar sustains otherwise disappear in the final 4-bit
            # rounding. Apply gain in the C64 quantizer, before that loss.
            set_gain(arrangement_path, 3.0)
        built = None
        previous_build = folder / "c64/build.json"
        if previous_build.exists():
            previous = json.loads(previous_build.read_text())
            program = Path(previous.get("program", ""))
            sym = Path(previous.get("symbols", ""))
            source_hashes = previous.get("source_sha256", {})
            if (previous.get("arrangement_sha256") == hashlib.sha256(arrangement_path.read_bytes()).hexdigest()
                    and previous.get("compression", {}).get("codec") == "dictionary8"
                    and {"pcm4_build.py", "pcm4_player.asm", "score_dictionary.py"} <= source_hashes.keys()
                    and all((HERE / filename).is_file()
                            and hashlib.sha256((HERE / filename).read_bytes()).hexdigest() == digest
                            for filename, digest in source_hashes.items())
                    and program.is_file() and sym.is_file()
                    and hashlib.sha256(program.read_bytes()).hexdigest() == previous.get("program_sha256")):
                from run_vice import symbols
                if symbols(sym) == previous.get("labels"):
                    built = previous
        if built is None:
            built = build(arrangement_path, folder / "c64", score_codec="dictionary8")
        record.update({"duration_s": built["duration_s"], "ticks": built["ticks"],
                       "program_bytes": built["program_bytes"], "program_end": built["program_end"],
                       "program_sha256": built["program_sha256"],
                       "prepared_sample_bytes": prepared["sample_bank_bytes_before_loop_expansion"]})
        if capture_audio:
            from pcm4_reference import expected_dac, verify_trace
            from run_vice import capture
            from verify_mod_timeline import verify_timeline

            original = verify_timeline(source, folder / "original", seconds=seconds)
            capture_path = folder / "vice/capture.json"
            dump = folder / "vice/registers.txt"
            audio = out / "audio" / f"{name}-c64.wav"
            try:
                prior_capture = json.loads(capture_path.read_text()) if capture_path.exists() else {}
            except (OSError, json.JSONDecodeError):
                prior_capture = {}
            runtime = {"played_tick_count": built["ticks"], "underrun_counter": 0}
            reuse_audio = (
                previous_record.get("status") == "verified"
                and previous_record.get("source_sha256") == provenance["sha256"]
                and previous_record.get("requested_seconds") == seconds
                and previous_record.get("program_sha256") == built["program_sha256"]
                and prior_capture.get("program_sha256") == built["program_sha256"]
                and prior_capture.get("profile") == PROFILE
                and prior_capture.get("score_duration_s") == built["duration_s"]
                and prior_capture.get("runtime", {}).get("registers") == runtime
                and prior_capture.get("runtime", {}).get("audio") == runtime
                and dump.is_file() and audio.is_file()
                and prior_capture.get("trace_sha256") == hashlib.sha256(dump.read_bytes()).hexdigest()
                and previous_record.get("audio_sha256") == hashlib.sha256(audio.read_bytes()).hexdigest())
            capture_receipt = (prior_capture if reuse_audio else
                               capture(Path(built["program"]), Path(built["symbols"]),
                                       folder / "vice", built["duration_s"], "registers"))
            arrangement = json.loads(arrangement_path.read_text())
            dac, arithmetic = expected_dac(arrangement)
            trace = verify_trace(dac, dump,
                                 capture_receipt["trace"]["first_sample_cycle"])
            (folder / "dac-check.json").write_text(json.dumps(trace, indent=2) + "\n")
            (folder / "arithmetic.json").write_text(json.dumps(arithmetic, indent=2) + "\n")
            if not trace["all_dac_bytes_match"]:
                raise ValueError(f"Actual DAC stream differs at {trace['mismatched_bytes']} samples")
            if not reuse_audio:
                capture_receipt = capture(Path(built["program"]), Path(built["symbols"]),
                                          folder / "vice", built["duration_s"], "audio")
                audio.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / "vice/stardust-listening.wav", audio)
            record.update({"audio": audio.relative_to(out).as_posix(),
                           "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                           "dac_samples_verified": trace["bytes_compared"],
                           "dac_mismatches": trace["mismatched_bytes"],
                           "runtime": capture_receipt["runtime"],
                           "capture_reused": reuse_audio,
                           "original_verification": original})
        target = out / "players" / f"{name}.prg"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built["program"], target)
        record.update({"program": target.relative_to(out).as_posix(),
                       "status": "verified" if capture_audio else "built",
                       "scope": "First passage of the source song; each instrument remains a reusable sample."})
    except Exception as error:
        record.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
    receipt_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def build_candidates(out: Path, names: tuple[str, ...] = CANDIDATES, seconds: float = 50,
                     capture_audio: bool = False, jobs: int = 2) -> dict:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = fetch_sources(songs=names)
    records = {}
    manifest = {"status": "running", "sources": sources, "expected_songs": list(names),
                "requested_seconds": seconds, "playback_profile": dict(PROFILE), "programs": []}
    manifest_path = out / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(build_candidate, name, out, seconds, capture_audio): name for name in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                records[name] = future.result()
            except Exception as error:
                records[name] = {"song": name, "status": "failed", "error": str(error)}
            manifest["programs"] = [records[key] for key in names if key in records]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"{name}: {records[name]['status']}" +
                  (f" — {records[name]['error']}" if "error" in records[name] else ""), flush=True)
    manifest["status"] = ("all_candidates_verified" if capture_audio else "all_candidates_built")
    if any(record["status"] == "failed" for record in records.values()):
        manifest["status"] = "incomplete"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    lines = ["# MOD candidate listening tests", "",
             "One current passage per song, using PAL / MOS8580 + digiboost.",
             "Originals are independent libopenmpt renders; C64 audio comes from the assembled program in VICE.",
             "The programs store reusable instruments, not full-song recordings.", "",
             f"Run status: **{manifest['status']}**. Requested passage: {seconds:g} seconds.", "",
             "| Song | Status | Seconds | Program | C64 audio | Original |",
             "| --- | --- | ---: | --- | --- | --- |"]
    for record in manifest["programs"]:
        name = record["song"]
        title = record.get("title", name).replace("|", "\\|")
        program = f"[PRG]({record['program']})" if "program" in record else "—"
        audio = f"[Listen]({record['audio']})" if "audio" in record else "—"
        original = f"[Original]({name}/original/original.wav)" if "original_verification" in record else "—"
        lines.append(f"| {title} | {record['status']} | {record.get('duration_s', 0):.3f} | {program} | {audio} | {original} |")
    lines.extend(("", "A verified entry includes the complete source tracker-flow check, native runtime counters",
                  "and an exact comparison of every DAC byte in this passage. See the per-song candidate.json",
                  "and dac-check.json receipts. Musical quality remains a listening judgment.", ""))
    (out / "CANDIDATES.md").write_text("\n".join(lines))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/rebuild")
    parser.add_argument("--candidates", action="store_true", help="Build all 13 new MOD test passages")
    parser.add_argument("--songs", nargs="+", choices=CANDIDATES, help="Build selected candidate passages")
    parser.add_argument("--seconds", type=float, default=50, help="Candidate passage duration (default: 50s)")
    parser.add_argument("--capture", action="store_true", help="Independently verify and record each candidate in VICE")
    parser.add_argument("--jobs", type=int, default=2, help="Concurrent candidate builds/captures (1..4)")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0 or not 1 <= args.jobs <= 4:
        parser.error("--seconds must be positive and --jobs must be between 1 and 4")
    if args.candidates or args.songs:
        names = tuple(dict.fromkeys(args.songs or CANDIDATES))
        result = build_candidates(args.out, names, args.seconds, args.capture, args.jobs)
        print(json.dumps({"status": result["status"], "songs": len(result["programs"]),
                          "manifest": str((args.out / "candidate-manifest.json").resolve()),
                          "listening_index": str((args.out / "CANDIDATES.md").resolve())}, indent=2))
        if result["status"] == "incomplete":
            raise SystemExit(1)
    else:
        if args.capture:
            parser.error("--capture requires --candidates or --songs")
        print(json.dumps(build_release(args.out), indent=2))


if __name__ == "__main__":
    main()
