"""Build a declared MOD phrase with one sampled channel and two tonal SID parts."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import urllib.request

import numpy as np

import build_mod_hybrid as hybrid
from instrument_library import load_library, receipt as library_receipt
from mod_sample_channel import CLOCK, PERIOD, PAULA, prepare_sample_channel

HERE = Path(__file__).resolve().parent


def source_mod(source: dict, out: Path) -> dict:
    slug = source.get("title_slug", "")
    cached = hybrid.base.MOD / "sources" / f"{slug}.mod"
    path = cached if slug and cached.exists() else out / "source.mod"
    if not path.exists():
        with urllib.request.urlopen(source.get("download_url") or source["source_url"], timeout=45) as response:
            data = response.read()
        if len(data) != source["bytes"]:
            raise ValueError("Downloaded MOD has the wrong size")
        path.write_bytes(data)
    if path.stat().st_size != source["bytes"] or hybrid.base.reference.digest(path) != source["sha256"]:
        raise ValueError("MOD differs from the instrument library's source receipt")
    if path.parent == out:
        hybrid.base.save(path.with_suffix(".source.json"), source)
    return hybrid.base.load_mod(path)


def source_block(raw: np.ndarray, sample: dict, position: float, advance: float) -> np.ndarray:
    """Follow original one-shot/loop lifetime for host-side synth tail gating."""
    indices = (position + np.arange(max(1, round(advance)))).astype(np.int64)
    if sample["loop_length"] > 2:
        start, length = sample["loop_start"], sample["loop_length"]
        # Paula first plays the complete instrument, then repeats its loop.
        wrapped = indices >= len(raw)
        indices[wrapped] = start + (indices[wrapped] - len(raw)) % length
    block = np.zeros(len(indices))
    valid = indices < len(raw)
    block[valid] = raw[indices[valid]]
    return block


def tonal_voice(mod: dict, timeline: list, ticks: list, channel: int,
                library: dict, start: float, end: float) -> tuple[list[list[int]], dict]:
    identifiers = sorted({t["channels"][channel]["playing_sample"] for t in ticks
                          if t["channels"][channel]["volume"] > 0})
    presets = {i: library["instruments"][i] for i in identifiers}
    if not presets or any(p["kind"] != "sid" or p["program"] not in {"pulse", "triangle"}
                          for p in presets.values()):
        raise ValueError("The tonal voice needs declared pulse or triangle instruments")
    sustains = {p["sustain"] for p in presets.values()}
    widths = {p["pulse_width"] for p in presets.values() if p["program"] == "pulse"}
    if len(sustains) != 1 or len(widths) > 1:
        raise ValueError("This voice requires one prewarmed sustain and one static pulse width")
    pitches = {i: hybrid.melody_pitch(mod, preset) for i, preset in presets.items()}
    raw = {s["id"]: np.frombuffer(s["data"], np.int8).astype(float) / 128
           for s in mod["samples"] if s["length"]}
    peaks = {i: max(float(np.sqrt(np.mean(raw[i][j:j + 256] ** 2)))
                    for j in range(0, len(raw[i]), 128)) for i in identifiers}
    rows, position, current = [], 0.0, 0
    for tick in timeline:
        if tick["time_s"] >= end - 1e-7:
            break
        state = tick["channels"][channel]
        selected = tick["time_s"] >= start - 1e-7
        if state["trigger"]:
            current, position = state["playing_sample"], float(state.get("offset", 0))
        frequency, control = 0.0, 0x19
        if current and state["period"]:
            if selected and (state.get("offset", 0) or
                             state.get("loop_sample", current) not in (0, current) or
                             state["playing_sample"] != current):
                raise ValueError("Tonal offsets or independent source changes need explicit support")
            advance = PAULA / state["period"] * tick["duration_s"]
            if selected and state["volume"] > 0:
                if current not in presets:
                    raise ValueError("Tonal channel has an undeclared instrument")
                block = source_block(raw[current], mod["samples"][current - 1], position, advance)
                if float(np.sqrt(np.mean(block * block))) > peaks[current] * presets[current]["rms_gate_ratio"]:
                    frequency = PAULA / state["period"] * pitches[current]["cycles_per_source_sample"]
                    control = presets[current]["control"]
            position += advance
        if selected:
            word = round(frequency * 2**24 / CLOCK)
            if not 0 <= word <= 65535:
                raise ValueError("Tonal frequency exceeds SID range")
            rows.append([word & 255, word >> 8, control])
    if len(rows) != len(ticks):
        raise ValueError("Tonal score and sampled timeline disagree")
    return rows, {"source_channel": channel + 1, "instruments": identifiers,
                  "source_triggers": sum(t["channels"][channel]["trigger"] for t in ticks),
                  "source_volumes": sorted({t["channels"][channel]["volume"] for t in ticks}),
                  "sustain": sustains.pop(), "pulse_width": next(iter(widths), 2048),
                  "pitch_analysis": pitches, "control_counts": dict(Counter(row[2] for row in rows)),
                  "scope": "Original note periods and source lifetime; quiet fixed sustain. Recorded timbre and continuous volume fades are approximated, not reproduced."}


def prepare(arrangement: dict, library: dict, out: Path) -> tuple[dict, list, dict]:
    mod = source_mod(library["source"], out)
    timeline = hybrid.base.build_timeline(mod)["ticks"]
    start, end = arrangement["source_range_s"]
    ticks = [t for t in timeline if start - 1e-7 <= t["time_s"] < end - 1e-7]
    channels = [arrangement["sample_channel"], *arrangement["sid_channels"]]
    if len(channels) != 3 or len(set(channels)) != 3 or any(c not in range(1, 5) for c in channels):
        raise ValueError("Declare three distinct source channels, one sampled and two tonal")
    if sorted(arrangement["omitted_channels"]) != sorted(set(range(1, 5)) - set(channels)):
        raise ValueError("Every omitted source channel must be declared")
    pcm = prepare_sample_channel(mod, ticks, channels[0] - 1, out, library["source"], start, end, library)
    voices, metadata = [], []
    for channel in channels[1:]:
        voice, details = tonal_voice(mod, timeline, ticks, channel - 1, library, start, end)
        voices.append(voice); metadata.append(details)
    rows = [a + b for a, b in zip(*voices)]
    before, after = (out / "data.asm").read_text().split("score:\n", 1)
    lines, index = [], 0
    for line in after.splitlines():
        if line.strip().startswith(".byte "):
            line += "," + ",".join(map(str, rows[index])); index += 1
        lines.append(line)
    if index != pcm["frames"]:
        raise ValueError("Unexpected sampled score format")
    constants = "".join(f'.label SID{i + 1}_{name} = {details[key]}\n'
                        for i, details in enumerate(metadata)
                        for name, key in [("SUSTAIN", "sustain"), ("PULSE", "pulse_width")])
    (out / "data.asm").write_text(constants + before + "score:\n" + "\n".join(lines) + "\n")
    synth = {"voices": metadata, "instrument_library": library_receipt(library)}
    hybrid.base.save(out / "expected-synth.json", {"frames": rows, "register_order": [0, 1, 4, 7, 8, 11]})
    hybrid.base.save(out / "synth-input.json", synth)
    return pcm, rows, synth


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arrangement", type=Path, default=HERE / "arrangements/hyperbased.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/hyperbased")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--budget", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    path = args.arrangement.resolve(); arrangement = json.loads(path.read_text())
    library = load_library(path.parent / arrangement["library"])
    preserved = hybrid.accepted_identity()
    pcm, rows, synth = prepare(arrangement, library, out)
    compiled = hybrid.base.reference.assemble("mod-channel-hybrid-player", out)
    (out / "player.prg").write_bytes(Path(compiled["program"]).read_bytes())
    captured = hybrid.base.reference.capture(compiled, out / "player", pcm["duration_s"])
    proof = hybrid.verify(compiled, captured, pcm, rows, out)
    proof["all_sample_inputs_match_independent_model"] = proof.pop("all_sample_inputs_match_accepted_solo")
    hybrid.base.save(out / "player-check.json", proof)
    report = {"title": arrangement["title"], "scope": arrangement["scope"],
              "arrangement": arrangement, "profile": captured["profile"],
              "pcm_input": pcm, "synth_input": synth, "build": compiled, "native_playback": proof}
    if args.capture:
        recorded = hybrid.base.reference.capture(compiled, out / "player", pcm["duration_s"], audio=True)
        report["audio"] = hybrid.audio(recorded, proof, pcm, out)
    if args.budget:
        from measure_budget import measure
        report["cpu_budget"] = measure(Path(compiled["program"]), compiled["symbols"], pcm["frames"], out / "budget")
    report["memory"] = {"prg_bytes": compiled["bytes"], "bank_bytes": pcm["bank_bytes"],
                        "score_bytes": pcm["frames"] * 11, "program_end": compiled["symbols"]["program_end"],
                        "unused_before_d000_bytes": 0xD000 - compiled["symbols"]["program_end"]}
    if hybrid.accepted_identity() != preserved:
        raise ValueError("Accepted references changed during the arrangement build")
    report["accepted_references_preserved"] = preserved
    report["source_sha256"] = {name: hybrid.base.reference.digest(HERE / name) for name in
                               ("build_mod_arrangement.py", "mod_sample_channel.py", "instrument_library.py",
                                "build_mod_hybrid.py", "mod-channel-hybrid-player.asm")}
    report["arrangement_sha256"] = hybrid.base.reference.digest(path)
    hybrid.base.save(out / "verification.json", report)
    print(json.dumps({"title": arrangement["title"], "duration_s": pcm["duration_s"],
                      "proof": proof, "audio": report.get("audio"), "cpu_budget": report.get("cpu_budget")}, indent=2))


if __name__ == "__main__":
    main()
