"""Build the complete Hyperbased three-channel SID/sample arrangement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_mod_arrangement as arrangement
import build_mod_hybrid as hybrid
from full_sample_channel import prepare_full_samples
from full_sid_score import prepare_full_sid
from full_score import pack_score
from verify_stream import verify

HERE = Path(__file__).resolve().parent


def prepare(out: Path) -> tuple[dict, dict, dict]:
    source = json.loads((HERE.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    mod = arrangement.source_mod(source, out)
    timeline = hybrid.base.build_timeline(mod)
    if timeline["termination"] != "end_of_order_list" or len(timeline["ticks"]) != 16692:
        raise ValueError("Expected one complete Hyperbased traversal to the end of its order list")
    samples = prepare_full_samples(mod, timeline["ticks"], out)
    synth = prepare_full_sid(mod, timeline["ticks"], out)
    if len(synth["voice_levels"]) != 2 or len(synth["voice_pulse_widths"]) != 2:
        raise ValueError("The full arrangement needs exactly two physical SID voice settings")
    settings = [{"sustain": level, "pulse_width": width}
                for level, width in zip(synth["voice_levels"], synth["voice_pulse_widths"])]
    packed = pack_score(samples["frames"], synth["rows"], samples["banks"], out,
                        len(timeline["ticks"]), sid_settings=settings)
    return samples, synth, {"compression": packed, "source_duration_s": timeline["duration_s"],
                             "orders": len(mod["orders"]), "termination": timeline["termination"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/hyperbased-full")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--budget", action="store_true")
    parser.add_argument("--assemble-only", action="store_true",
                        help="Prepare and assemble without invoking VICE")
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    preserved = hybrid.accepted_identity()
    excerpt = {name: hybrid.base.reference.digest(HERE / "results/hyperbased" / name)
               for name in ("player.prg", "hybrid.wav", "verification.json")}
    samples, synth, score = prepare(out)
    compiled = hybrid.base.reference.assemble("full-song-player", out)
    (out / "player.prg").write_bytes(Path(compiled["program"]).read_bytes())
    report = {"title": "Hyperbased", "source_range_s": [0, score["source_duration_s"]],
              "scope": "Complete 333.84-second three-channel arrangement. Source channel 4 is sampled, channels 2 and 1 use SID recipes, and channel 3 remains omitted. Sample bandwidth/volume are quantized; chords are arpeggiated. This is not an exact four-channel MOD reproduction.",
              "pcm_input": samples["metadata"], "synth_input": {k: v for k, v in synth.items() if k != "rows"},
              "score": score, "build": compiled}
    if not args.assemble_only:
        captured = hybrid.base.reference.capture(compiled, out / "player", samples["metadata"]["duration_s"])
        proof = verify(compiled, captured, samples["metadata"], synth["rows"], out)
        report.update(profile=captured["profile"], native_playback=proof)
        if args.capture:
            audio = hybrid.base.reference.capture(compiled, out / "player", samples["metadata"]["duration_s"], audio=True)
            report["audio"] = hybrid.audio(audio, proof, samples["metadata"], out)
        if args.budget:
            from measure_budget import measure
            report["cpu_budget"] = measure(Path(compiled["program"]), compiled["symbols"],
                                             samples["metadata"]["frames"], out / "budget")
    elif args.capture or args.budget:
        raise ValueError("--assemble-only cannot capture or profile")
    report["memory"] = {"prg_bytes": compiled["bytes"], "program_end": compiled["symbols"]["program_end"],
                        "bank_bytes": samples["metadata"]["bank_bytes"],
                        "unused_before_d000_bytes": 0xD000 - compiled["symbols"]["program_end"]}
    if hybrid.accepted_identity() != preserved:
        raise ValueError("Accepted references changed during the full-song build")
    if any(hybrid.base.reference.digest(HERE / "results/hyperbased" / name) != digest
           for name, digest in excerpt.items()):
        raise ValueError("Accepted Hyperbased excerpt changed during the full-song build")
    report["accepted_references_preserved"] = preserved
    report["accepted_hyperbased_excerpt_preserved"] = excerpt
    names = ["build_full_hyperbased.py", "full_sample_channel.py", "full_sid_score.py", "full_score.py",
             "full-song-player.asm", "verify_stream.py"]
    report["source_sha256"] = {name: hybrid.base.reference.digest(HERE / name) for name in names}
    library = HERE / "instruments/hyperbased-full-samples"
    report["sample_library_sha256"] = {str(path.relative_to(HERE)): hybrid.base.reference.digest(path)
                                        for path in sorted(library.iterdir()) if path.is_file()}
    hybrid.base.save(out / "verification.json", report)
    print(json.dumps({"duration_s": samples["metadata"]["duration_s"], "program_bytes": compiled["bytes"],
                      "samples": samples["metadata"]["input_codes"], "score": score,
                      "native_playback": report.get("native_playback"), "audio": report.get("audio"),
                      "cpu_budget": report.get("cpu_budget")}, indent=2))


if __name__ == "__main__":
    main()
