"""Verify original melody channels alone before arranging accompaniment."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

import audition_samples
from aligned_melody_banks import align
import build_auditions as auditions
import build_mod_arrangement as arrangement
import build_mod_hybrid as hybrid
from full_sample_channel import prepare_full_samples
from full_score import pack_score
from measure_budget import measure
from verify_stream import verify

HERE = Path(__file__).resolve().parent
MOD = HERE.parent / "mod-hybrid"


def prepare(mod: dict, ticks: list, channel: int, source: dict, out: Path) -> tuple[dict, list, dict, str]:
    settings = [{"sustain": 1, "pulse_width": 1966}, {"sustain": 1, "pulse_width": 2048}]
    try:
        samples = audition_samples.prepare(mod, ticks, channel - 1, out)
    except ValueError as error:
        if "Audible gain changed" not in str(error):
            raise
    else:
        rows = [[0, 0, 25, 0, 0, 25] for _ in samples["frames"]]
        auditions.write_score(samples, rows, settings, out)
        return samples["metadata"], rows, {"engine": "accepted static-gain sampler", "gain_quantum": 1}, "mod-channel-hybrid-player"
    # Keep the original melody when it changes volume. The existing advanced
    # SID-voice renderer changes gain banks while retaining its logical cursor.
    # It uses the same eight-bit/126-cycle sample-and-hold signal path.
    if any(abs(tick["duration_s"] - .02) > 1e-9 for tick in ticks):
        raise ValueError("Advanced melody gain-bank checks currently require 20-ms ticks")
    local = copy.deepcopy(ticks)
    for index, tick in enumerate(local):
        tick["time_s"] = index * .02
    identifiers = {tick["channels"][channel - 1]["playing_sample"] for tick in local} - {0}
    failures = []
    for quantum in (1, 2, 3, 4, 8, 16):
        candidate = out / "gain-study" / f"q{quantum}"
        candidate.mkdir(parents=True, exist_ok=True)
        try:
            samples = prepare_full_samples(mod, local, candidate, channel=channel - 1,
                source_receipt=source, library_dir=candidate / "instruments",
                extra_decimation={identifier: 1 for identifier in identifiers},
                gain_quantum=quantum, allow_initial_silence=False)
            samples = align(samples, candidate)
            rows = [[0, 0, 25, 0, 0, 25] for _ in samples["frames"]]
            pack_score(samples["frames"], rows, samples["banks"], candidate, len(local), sid_settings=settings)
            # Test the real assembler budget, not a guessed bank-only limit.
            compiled = hybrid.base.reference.assemble("full-song-player", candidate)
            shutil.copyfile(candidate / "data.asm", out / "data.asm")
            shutil.copyfile(candidate / "expected-input.bin", out / "expected-input.bin")
            metadata = samples["metadata"]
            metadata["source_range_s"] = [ticks[0]["time_s"], ticks[-1]["time_s"] + ticks[-1]["duration_s"]]
            auditions.save(out / "input.json", metadata)
            return metadata, rows, {"engine": "existing gain-bank SID-voice sampler", "gain_quantum": quantum,
                "gain_error_units": metadata["gain_quantization_error_units"],
                "lossless_loop_alignment": samples["alignment_proof"],
                "candidate_program_bytes": compiled["bytes"], "rejected_gain_preparations": failures}, "full-song-player"
        except (ValueError, RuntimeError) as error:
            failures.append({"gain_quantum": quantum, "error": str(error)})
    raise ValueError(f"Original melody cannot fit the declared gain-bank budgets: {failures}")


def original_reference(mod: dict, ticks: list, channel: int, out: Path) -> dict:
    from reference import render_timeline_pcm
    local = copy.deepcopy(ticks)
    start = ticks[0]["time_s"]
    for tick in local:
        tick["time_s"] -= start
        for index, state in enumerate(tick["channels"]):
            if index != channel - 1:
                state["volume"] = 0
    duration = ticks[-1]["time_s"] + ticks[-1]["duration_s"] - start
    signal = render_timeline_pcm(mod, {"ticks": local, "duration_s": duration}, 22050)
    # The four-channel reference mixer divides by four. Undo that fixed scale
    # for this isolated original; it is never mixed into the C64 recording.
    sf.write(out / "original-melody.wav", signal * 4, 22050, subtype="PCM_16")
    return {"source_channel": channel, "duration_s": len(signal) / 22050,
            "sha256": auditions.digest(out / "original-melody.wav"),
            "processing": "Separate original-source channel reference, constant gain4 undoing the reference mixer's four-channel scale. Not C64 audio; never mixed into delivered native audio."}


def build(config: dict, root: Path) -> dict:
    slug, channel = config["slug"], config["melody_channel"]
    out = root / slug; out.mkdir(parents=True, exist_ok=True)
    before = auditions.protected()
    receipt = json.loads((MOD / "sources" / f"{slug}.source.json").read_text())
    source = dict(receipt, title_slug=slug)
    mod = arrangement.source_mod(source, out)
    timeline = hybrid.base.build_timeline(mod)["ticks"]
    ticks = timeline[config["start_tick"]:config["end_tick"]]
    if not ticks[0]["channels"][channel - 1]["trigger"]:
        raise ValueError("Melody check must start at a real melody note")
    metadata, rows, preparation, runtime = prepare(mod, ticks, channel, source, out)
    compiled = hybrid.base.reference.assemble(runtime, out)
    shutil.copyfile(compiled["program"], out / "player.prg")
    recorded = hybrid.base.reference.capture(compiled, out / "player", metadata["duration_s"])
    proof = verify(compiled, recorded, metadata, rows, out)
    audio_capture = hybrid.base.reference.capture(compiled, out / "player", metadata["duration_s"], audio=True)
    audio = hybrid.audio(audio_capture, proof, metadata, out)
    audio_file = root / f"{slug}-melody.wav"
    shutil.copyfile(out / "hybrid.wav", audio_file)
    original = original_reference(mod, ticks, channel, out)
    budget = measure(Path(compiled["program"]), compiled["symbols"], len(rows), out / "budget")
    if auditions.protected() != before:
        raise ValueError("An accepted reference or player changed during melody verification")
    report = {"slug": slug, "status": "recorded_melody_only", "listening_status": "unreviewed",
              "melody_source_channel": channel, "source_range_s": metadata["source_range_s"],
              "source_sha256": mod["sha256"], "preparation": preparation, "build": compiled,
              "native_playback": proof, "audio": audio, "audio_file": str(audio_file),
              "cpu_budget": budget,
              "original_reference": original, "source_config": config,
              "scope": "The original melody channel alone through SID voice3, using reusable eight-bit instrument banks. Both ordinary SID voices rest. Identify and validate this melody before adding accompaniment; no substitute kick, arpeggio or guessed oscillator root replaces it."}
    approval = json.loads((HERE / "audition-listening.json").read_text())["songs"].get(slug, {}).get("melody_solo", {})
    if (approval.get("status") == "accepted" and approval.get("audio_sha256") == audio["output_sha256"]
            and approval.get("program_sha256") == compiled["program_sha256"]):
        report.update(listening_status="accepted", user_feedback=approval["feedback"])
    auditions.save(out / "melody-check.json", report)
    print(json.dumps({"slug": slug, "channel": channel, "source_range_s": metadata["source_range_s"],
                      "audio_file": str(audio_file), "gain_quantum": preparation["gain_quantum"],
                      "gain_error_units": preparation.get("gain_error_units", [0, 0]),
                      "program_bytes": compiled["bytes"], "passed": proof["passed"]}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, default=HERE / "melody-checks.json")
    parser.add_argument("--songs", nargs="+")
    parser.add_argument("--out", type=Path, default=HERE / "results/auditions-20s/melody-checks")
    args = parser.parse_args()
    for song in json.loads(args.plans.read_text())["songs"]:
        if not args.songs or song["slug"] in args.songs:
            build(song, args.out.resolve())


if __name__ == "__main__":
    main()
