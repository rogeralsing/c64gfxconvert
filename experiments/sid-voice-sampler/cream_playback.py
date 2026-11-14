"""Port Cream's approved passage using the canonical native mixer and decoder.

The accepted passage is original MOD time 17.92..44.80, not the song opening.
Its instrument programs stay separate from Hyperbased's arrangement.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

import full_length_playback as playback
import full_length_runtime as runtime
import full_length_score as score
import native_support as support

HERE = Path(__file__).resolve().parent
MODES = {"all": (True, True, True), "sid-1": (True, False, False),
         "sid-2": (False, True, False), "sid-3": (False, False, True),
         "muted": (False, False, False)}
GAIN = 8.0
TICK_FIELDS = {name: index for name, index in runtime.TICK_FIELDS.items() if index >= 12}
TICK_FIELDS.update({"sid1_frequency_dictionary_index": 0, "sid1_continuous_envelope": 1,
                   "sid1_control": 2, "sid1_pulse_low": 3, "sid1_pulse_high": 4,
                   "sid1_sustain_release": 5, "sid2_frequency_low": 6,
                   "sid2_frequency_high": 7, "sid2_control": 8, "sid2_pulse_low": 9,
                   "sid2_pulse_high": 10, "sid2_sustain_release": 11})


def protected_hashes(*, full: bool = False) -> dict:
    paths = [*HERE.glob("references/**/*.prg"), *HERE.glob("references/**/*.wav"),
             *HERE.glob("work/hyperbased/full-linus-mix/*.prg"),
             *HERE.glob("work/hyperbased/full-linus-mix/*.wav"),
             *HERE.glob("work/hyperbased/linus-mix/*.prg"),
             *HERE.glob("work/hyperbased/linus-mix/*.wav")]
    if full:
        paths += [*HERE.glob("work/cream/linus-mix/*.prg"),
                  *HERE.glob("work/cream/linus-mix/*.wav")]
    return {str(p.relative_to(HERE)): support.digest(p) for p in paths}


def _record(builds: dict, proofs: dict, out: Path, duration: float, frames: int, *,
            full: bool = False) -> dict:
    """Record full workloads independently; compare the mix before delivery."""
    audio_builds = dict(builds)
    audio_builds["static-control"] = playback.static_control(
        builds["muted"], out / "static-control", frames)

    def capture(item):
        name, build = item
        epoch = proofs["all" if name == "static-control" else name]["first_latch_cycle"]
        folder = out / "programs" / name / "audio"
        saved = folder / "receipt.json"
        if saved.exists():
            receipt = json.loads(saved.read_text())
            media = Path(receipt["media"])
            if (receipt["program_sha256"] == build["program_sha256"]
                    and receipt["profile"] == support.profile().PROFILE
                    and media.exists() and support.digest(media) == receipt["media_sha256"]):
                return name, playback.read_audio_capture(receipt, duration, epoch, frames)
        signal = playback.capture_audio(build, folder, duration, epoch, frames)
        return name, signal

    with ThreadPoolExecutor(max_workers=6) as pool:
        captured = dict(pool.map(capture, audio_builds.items()))
    peak = max(float(np.max(abs(signal))) for name, (signal, _, _) in captured.items()
               if name not in ("muted", "static-control"))
    gain = min(GAIN, .92 / peak) if full and peak else GAIN
    if peak * gain >= 1:
        raise ValueError("Cream's approved fixed listening gain would clip")
    muted_lsb = float(np.max(abs(captured["muted"][0] - captured["static-control"][0]))
                      * gain * 32768)
    mute_check = {"passed": muted_lsb <= 1, "maximum_pcm16_lsb_difference": muted_lsb}
    support.save(out / "mute-control-check.json", mute_check)
    if not mute_check["passed"]:
        raise ValueError("Cream's muted producer differs from its independent static SID control")

    from cream_reference import compare, compare_full
    reference = (compare_full if full else compare)(captured["all"][0], captured["all"][1])
    support.save(out / "audio-reference-check.json", reference)
    if not reference["passed"]:
        raise ValueError("Cream differs from its approved sound; inspect audio-reference-check.json")
    audio = {}
    for name in ("all", "sid-1", "sid-2", "sid-3"):
        signal, rate, receipt = captured[name]
        filename = f"{name}.wav"
        sf.write(out / filename, signal * gain, rate, subtype="PCM_16")
        audio[name] = {"file": filename, "sha256": support.digest(out / filename),
                       "frames": len(signal), "rate": rate, "duration_s": len(signal) / rate,
                       "listening_gain": gain, "raw_capture_sha256": receipt["media_sha256"],
                       "profile": receipt["profile"],
                       "processing": "Independent actual VICE capture, native-clock crop, DC removal and one shared constant gain. No host mixing, EQ, alignment or dynamics."}
    return {"audio": audio, "mute_control": mute_check, "audio_reference": reference}


def _loader_arena(ledger: dict, score_bytes: int) -> tuple[int, int]:
    """Choose unused RAM visible when BASIC SYS first jumps to the bootstrap."""
    score_start = ledger["score_address"]
    score_end = score_start + score_bytes
    candidates = []
    for low, high in ledger["remaining_arenas"]:
        spans = [(low, high)]
        if low < score_end and score_start < high:
            spans = [(low, max(low, score_start)), (min(high, score_end), high)]
        # BASIC ROM is still mapped at the first jump; the loader banks it out.
        for start, stop in spans:
            for visible_start, visible_stop in ((0x0801, 0xa000), (0xc000, 0xd000)):
                first, last = max(start, visible_start), min(stop, visible_stop)
                if first < last:
                    candidates.append((first, last))
    if not candidates:
        raise ValueError("No visible unused RAM remains for Cream's startup loader")
    return max(candidates, key=lambda pair: pair[1] - pair[0])


def run(out: Path, *, assemble_only: bool = False, full: bool = False) -> dict:
    import cream_instruments as instruments

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    protected = protected_hashes(full=full)
    prepared = instruments.prepare(out / "instruments", **({"full": True} if full else {}))
    expected = instruments.expected_input(prepared)
    (out / "expected-input.bin").write_bytes(expected)
    rows, data, ledger = playback.link_instruments(prepared, out / "linked")
    physical_raw = (out / "linked/physical-rows.bin").read_bytes()
    physical = [list(physical_raw[i:i + 24]) for i in range(0, len(physical_raw), 24)]
    packed = score.prepare(rows, out / "score", ledger["score_address"])
    if packed["score_bytes"] > ledger["score_capacity"]:
        raise ValueError("Cream's compact score exceeds its free native RAM arena")
    ledger.update(score_bytes=packed["score_bytes"], score_history_bytes=packed["history_bytes"])
    coverage = playback.write_coverage(out) if full else None
    if full:
        ledger["gain_lookup_bytes"] = ledger.pop("triangle_bytes")
    arena = (_loader_arena(ledger, packed["score_bytes"]) if full
             else tuple(ledger["remaining_arenas"][0]))
    builds = {name: runtime.build(out / "programs" / name, data, Path(packed["score_asm"]),
                                 enabled, loader_arena=arena,
                                 sid_programs_asm=Path(prepared["sid_programs_asm"]),
                                 **({"pcm_fractional": True} if full else {}))
              for name, enabled in MODES.items()}
    for build in builds.values():
        build["tick_record_fields"] = dict(TICK_FIELDS)
        if full:
            build["tick_record_fields"].update(sid1_frequency_low=0,
                sid1_frequency_high_and_continuous_flag=1, pcm_q8_step_low=12,
                pcm_q8_step_high=13, pcm_gain_table_page=14, pcm_fraction_reset=15)
            for obsolete in ("sid1_frequency_dictionary_index", "sid1_continuous_envelope",
                             "triangle_negative_step_low", "triangle_negative_step_high",
                             "triangle_table_page", "triangle_reset"):
                build["tick_record_fields"].pop(obsolete, None)
        support.save(Path(build["program"]).parent / "build.json", build)
    duration = len(expected) * support.PERIOD / support.CLOCK
    result = {"scope": ("Complete Cream three-voice arrangement; omissions and new SID approximations are explicit."
                        if full else "Cream approved reference passage only; not a complete-song port."),
              "full_song": full,
              "source": prepared["source"], "source_interval_s": prepared["report"]["source_range_s"],
              "frames": len(rows), "duration_s": duration, "nominal_duration_s": len(rows) / 50,
              "program": {k: v for k, v in builds["all"].items() if k != "symbols"},
              "memory": ledger, "score": packed, "arrangement": prepared["report"],
              "protected_hashes": protected,
              "source_sha256": {str(p.relative_to(HERE)): support.digest(p) for p in
                  [HERE / "cream_instruments.py", HERE / "cream_sid.asm", Path(__file__),
                   HERE / "cream_reference.py", HERE / "build_linus_mix.py",
                   *([HERE / "cream_fractional.py"] if full else []),
                   *sorted((HERE / "native_instruments/cream").glob("*.json"))]}}
    if full:
        result["coverage"] = coverage
        result["arrangement"]["SID_volume_policy"] = (
            "Ordinary SID voices retain the approved SR$10 continuous-envelope policy: "
            "zero versus nonzero source volume is represented, but nonzero volume slides "
            "are not reproduced. PCM gain changes are preserved separately.")
        result["arrangement"]["omissions"] = (
            "C1 is omitted outside its explicit introduction allocation. "
            "Quiet gaps in another allocated voice are not filled automatically.")
    (out / ".gitignore").write_text("*\n!.gitignore\n!player.prg\n!all.wav\n!sid-[1-3].wav\n!verification.json\n!audio-reference-check.json\n!coverage.json\n!rebuild-check.json\n!README.md\n")
    support.save(out / "verification.json", result)
    if assemble_only:
        shutil.copyfile(builds["all"]["program"], out / "player.prg")
        return result

    def verify(item):
        name, build = item
        folder = out / "programs" / name
        receipt = support.capture(build, folder / "registers", duration)
        support.save(folder / "register-receipt.json", receipt)
        proof = playback.verify_trace(build, receipt, prepared, physical, expected, folder, MODES[name])
        return name, proof

    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs = dict(pool.map(verify, builds.items()))
    if len({p["first_latch_cycle"] for p in proofs.values()}) != 1:
        raise ValueError("Cream solo programs changed the shared native startup epoch")
    result["native"] = proofs
    result["deadlines"] = playback.measure_deadlines(
        builds["all"], prepared["frame_sample_counts_exact"], out / "deadlines")
    from verify_prg_startup import verify as verify_startup
    startup = verify_startup(builds["all"], Path(builds["all"]["startup_loader"]["native_program"]),
                             out / "autostart", mode=2, full=True)
    result["autostart"] = playback.verify_trace(builds["all"], startup, prepared, physical,
                                                expected, out / "autostart", MODES["all"])
    result["autostart"].update(mode=2, restored_native_ram=startup["restored_native_ram"])
    support.save(out / "verification.json", result)
    from native_instruments.measure_music_budget import measure
    budget = measure(Path(builds["all"]["program"]), builds["all"]["symbols"],
                     prepared["frame_sample_counts_exact"], out / "cpu")
    result["cpu"] = playback.normalize_budget(budget)
    support.save(out / "verification.json", result)
    if not budget["passed"]:
        raise ValueError(f"Cream CPU timing proof failed: {budget.get('failures')}")
    result.update(_record(builds, proofs, out, duration, len(rows), full=full))
    result["protected_unchanged"] = protected == protected_hashes(full=full)
    if not result["protected_unchanged"]:
        raise ValueError("A frozen reference or Hyperbased artifact changed")
    shutil.copyfile(builds["all"]["program"], out / "player.prg")
    support.save(out / "verification.json", result)
    return result
