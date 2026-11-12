"""Build and capture the single canonical Hyperbased native SID arrangement."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
import soundfile as sf

import native_support as support

HERE = Path(__file__).resolve().parent
APPROVED_WAV = {
    "sid-1": "c3f9d0f295705641d96c6992fb2d6798326f63fbb34dd96e6ed42cdbe843745b",
    "sid-3": "fb1af01bf2e098ed40f65fe03f30eaa09538125626ff58ab5225a23019c8fbc7",
}


def reference_comparison(name: str, signal: np.ndarray, rate: int) -> dict:
    """Reject musical audio regressions while allowing measured capture noise.

    Older and current crops have different absolute emulator start times.
    Their current observed deltas are at most 80 PCM16 LSB peak and 22 RMS at gain 8.
    The bound below leaves a small margin without permitting timbre changes.
    Native register values and event phases are checked independently.
    """
    reference = HERE / "references/hyperbased-stems" / f"{name}.wav"
    if not reference.exists() or support.digest(reference) != APPROVED_WAV[name]:
        raise ValueError(f"Missing or changed approved listening reference: {reference}")
    old, old_rate = sf.read(reference, dtype="int16")
    if old_rate != rate or len(old) != len(signal):
        raise ValueError("Approved stem and current capture have different time axes")
    buffer = io.BytesIO()
    sf.write(buffer, signal * 8, rate, format="WAV", subtype="PCM_16")
    encoded = buffer.getvalue()
    buffer.seek(0)
    actual = sf.read(buffer, dtype="int16")[0]
    difference = actual.astype(np.int32) - old.astype(np.int32)
    peak = int(np.max(np.abs(difference)))
    rms = float(np.sqrt(np.mean(difference.astype(float) ** 2)))
    result = {"passed": peak <= 96 and rms <= 25,
              "comparison_gain": 8, "maximum_pcm16_lsb_difference": peak,
              "rms_pcm16_lsb_difference": rms,
              "peak_limit_pcm16_lsb": 96, "rms_limit_pcm16_lsb": 25,
              "wav_at_reference_gain_sha256": hashlib.sha256(encoded).hexdigest(),
              "no_alignment_or_audio_correction": True}
    if not result["passed"]:
        raise ValueError(f"Approved {name} sound changed beyond capture-noise bounds: {result}")
    return result


def variant(folder: Path, linked_dir: Path, linked: dict, name: str) -> tuple[dict, list, dict]:
    """Mute physical outputs while retaining the entire producer workload."""
    folder.mkdir(parents=True, exist_ok=True)
    enabled = {"all": (True, True, True), "sid-1": (True, False, False),
               "sid-2": (False, True, False), "sid-3": (False, False, True),
               "muted": (False, False, False)}[name]
    constants = {"SID1_SUSTAIN": 2 if enabled[0] else 0,
                 "SID2_SUSTAIN": 15 if enabled[1] else 0,
                 "SID3_SUSTAIN": 15 if enabled[2] else 0,
                 "SID_OUTPUT_MODE": 15 if enabled[2] else 143,
                 "SID2_LATCH_CONTROL": 17 if enabled[1] else 25,
                 "SID2_RELEASE_CONTROL": 1 if enabled[1] else 9}
    data = (linked_dir / "data.asm").read_text()
    if not re.search(r"(?m)^\.label C3_SILENT_VARIANT = ", data):
        data = f'.label C3_SILENT_VARIANT = {linked["c3"]["variants"][-1]["id"]}\n' + data
    for key, value in constants.items():
        pattern = rf"(?m)^\.label {key} = \d+$"
        data, count = re.subn(pattern, f".label {key} = {value}", data)
        if not count and key.startswith("SID2_") and key.endswith("CONTROL"):
            data = f".label {key} = {value}\n" + data
        elif count != 1:
            raise ValueError(f"Expected one startup output constant: {key}")
    rows = [row[:3].copy() for row in linked["rows"]]
    score_address = linked["labels"]["score"]
    original_score = linked_dir / f"{score_address:04x}-score.bin"
    if not enabled[0]:
        score = bytearray(original_score.read_bytes())
        for index in range(len(rows)):
            score[index * 12 + 6:index * 12 + 9] = bytes([0, 0, 25])
            rows[index] = [0, 0, 25]
        path = folder / "muted-sid1-score.bin"
        path.write_bytes(score)
        data = data.replace(str(original_score.resolve()), str(path.resolve()))
    (folder / "data.asm").write_text(data)
    shutil.copyfile(linked_dir / "rle/expected-input.bin", folder / "expected-input.bin")
    build = support.assemble("linus-mix-player", folder)
    return build, rows, {"enabled_physical_outputs": list(enabled),
                         "constants": constants,
                         "sid3_input_stream_retained": True,
                         "sid2_input_stream_retained": True,
                         "source_muting": "SID1 uses zero-frequency TEST/triangle score states. SID2 keeps TEST set in its sampler control writes. SID3 uses its native output-disable bit. Excluded envelopes have zero sustain. Every native producer and both sample clocks continue unchanged."}


def check_variant(full: dict, solo: dict, enabled: list[bool], frames: int) -> dict:
    """Allow only named immediate operands and SID1 score mute fields."""
    original = Path(full["program"]).read_bytes()
    actual = Path(solo["program"]).read_bytes()
    mute_labels = {"SID1_SUSTAIN", "SID2_SUSTAIN", "SID3_SUSTAIN", "SID_OUTPUT_MODE",
                   "SID2_LATCH_CONTROL", "SID2_RELEASE_CONTROL"}
    full_layout = {key: value for key, value in full["symbols"].items() if key not in mute_labels}
    solo_layout = {key: value for key, value in solo["symbols"].items() if key not in mute_labels}
    if len(original) != len(actual) or full_layout != solo_layout:
        raise ValueError("A physical stem changed the runtime layout")
    load = int.from_bytes(original[:2], "little")
    labels = full["symbols"]
    allowed = {labels[f"sid{voice}_sustain_load"] - load + 3 for voice in range(1, 4)}
    allowed.add(labels["master_output_load"] - load + 3)
    for label, address in labels.items():
        if label.startswith(("sid2_latch_load_", "sid2_release_load_")):
            if 0x0400 <= address < 0x0500:
                address = labels["sid2_image"] + address - 0x0400
            elif 0x0500 <= address < 0x0600:
                address = labels["sid2_pending_image"] + address - 0x0500
            allowed.add(address - load + 3)
    if not enabled[0]:
        score = labels["score"] - load + 2
        allowed.update(score + frame * 12 + field for frame in range(frames) for field in (6, 7, 8))
    changed = {index for index, pair in enumerate(zip(original, actual)) if pair[0] != pair[1]}
    if changed - allowed:
        raise ValueError(f"Stem changed undeclared program bytes: {sorted(changed - allowed)[:12]}")
    return {"passed": True, "same_runtime_layout": True,
            "only_declared_output_mutes_differ": True, "changed_program_bytes": len(changed)}


def static_control(muted: dict, folder: Path) -> dict:
    """Keep identical SID initialization, then record an independently static SID.

    Patch machine code after assembly so instruction addresses, code-copy costs,
    startup delays and all pre-music SID events stay identical to the mute run.
    The substituted timer-start sequence still takes eight CPU cycles.
    """
    folder.mkdir(parents=True, exist_ok=True)
    original = Path(muted["program"]).read_bytes()
    raw = bytearray(original)
    load = int.from_bytes(raw[:2], "little")
    labels = muted["symbols"]
    start = labels["song_started"] - load + 2
    if raw[start:start + 6] != bytes([0x8d, 0x0e, 0xdd, 0x8d, 0x0f, 0xdc]):
        raise ValueError("Unexpected native timer-start sequence")
    raw[start:start + 6] = bytes([0xa9, 0, 0x8d, 0x0e, 0xdd, 0xea])
    hold = 0xc600
    if load + len(raw) - 2 > hold:
        raise ValueError("Static-control delay would overlap the native image")
    wait = labels["wait_start"] - load + 2
    raw[wait:wait + 3] = bytes([0x4c, hold & 255, hold >> 8])
    raw.extend(bytes(hold - (load + len(raw) - 2)))
    # Approximately21.2seconds, with all CIA timers stopped and no SID writes.
    code = [0xa9, 64, 0x85, 0xfc, 0xa0, 255, 0xa2, 255, 0xca, 0xd0, 0xfd,
            0x88, 0xd0, 0xf8, 0xc6, 0xfc, 0xd0, 0xf2,
            0xa9, 0xe8, 0x85, 0x0a, 0xa9, 3, 0x85, 0x0b,
            0x4c, labels["done"] & 255, labels["done"] >> 8]
    raw.extend(code)
    path = folder / "static.prg"
    path.write_bytes(raw)
    return dict(muted, program=str(path.resolve()), program_sha256=support.digest(path),
                bytes=len(raw), source_sha256=None)


def memory_budget(build: dict, linked: dict) -> dict:
    raw = Path(build["program"]).read_bytes()
    load = int.from_bytes(raw[:2], "little")
    end = load + len(raw) - 2
    labels = build["symbols"]
    copied = sum(labels[stop] - labels[start] for start, stop in
                 (("mix_samples", "mix_end"), ("nmi_common", "nmi_end"),
                  ("c3_produce_block", "c3_producer_end")))
    return {"loaded_image_start": load, "loaded_image_end_exclusive": end,
            "loaded_image_bytes": len(raw) - 2,
            "independent_instrument_and_score_data_bytes": linked["resident_data_bytes"],
            "copied_zero_page_code_bytes": copied, "zero_page_state_reserved_bytes": 30,
            "native_buffers_phase_pages_ring_bytes": 1280, "stack_page_reserved_bytes": 256,
            "interrupt_vector_bytes": 2,
            "resident_total_including_reserved_stack_bytes": len(raw) - 2 + copied + 30 + 1280 + 256 + 2,
            "contiguous_free_before_io_bytes": 0xd000 - end,
            "conservative_free_upper_ram_bytes": 0x1f00,
            "scope": "Conservative resident image plus separate low-RAM work areas; image alignment holes counted as occupied. SID I/O remains visible."}


def run(out: Path, *, assemble_only: bool = False) -> dict:
    from native_instruments.prepare_music import prepare
    from native_instruments.verify_music import verify
    from native_instruments.measure_ring import measure as measure_ring
    from native_instruments.measure_music_budget import measure as measure_budget

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prepared = prepare(out / "build")
    linked = prepared["linked"]
    linked_dir = Path(prepared["paths"]["linked"])
    pcm = linked["input"]
    variants = {name: variant(out / "programs" / name, linked_dir, linked, name)
                for name in ("all", "sid-1", "sid-2", "sid-3", "muted")}
    for name, (build, _, isolation) in variants.items():
        isolation.update(check_variant(variants["all"][0], build,
                                       isolation["enabled_physical_outputs"], pcm["frames"]))
    shutil.copyfile(variants["all"][0]["program"], out / "player.prg")
    result = {"scope": "First twenty seconds of Hyperbased, all four original channels assigned to three physical SID outputs.",
              "profile": support.profile().PROFILE,
              "data": prepared["verification"], "input": pcm,
              "program_sha256": support.digest(out / "player.prg"),
              "memory": memory_budget(variants["all"][0], linked),
              "variants": {name: {"build": value[0], "isolation": value[2]}
                           for name, value in variants.items()}}
    support.save(out / "input.json", pcm)
    support.save(out / "memory-budget.json", result["memory"])
    support.save(out / "preparation.json", json.loads((Path(prepared["paths"]["root"]) / "preparation.json").read_text()))
    if assemble_only:
        support.save(out / "verification.json", result)
        return result

    def capture_native(item):
        name, (build, rows, isolation) = item
        folder = out / "programs" / name
        captured = support.capture(build, folder / "registers", pcm["duration_s"])
        proof = verify(build, captured, pcm, rows, folder,
                       linked_dir / "c3/expected-high.bin", directmeta=linked["c3"],
                       sid2_muted=not isolation["enabled_physical_outputs"][1])
        if proof["first_latch_cycle"] != 2246223:
            raise ValueError("Canonical capture startup phase differs from the calibrated approved reference")
        proof["absolute_startup_phase_is_a_gate"] = True
        proof["required_first_latch_cycle"] = 2246223
        support.save(folder / "player-check.json", proof)
        support.save(folder / "registers-receipt.json", captured)
        return name, proof

    with ThreadPoolExecutor(max_workers=3) as pool:
        native = dict(pool.map(capture_native, variants.items()))
    result["native"] = native
    support.save(out / "player-check.json", native["all"])
    full = variants["all"][0]
    result["ring"] = measure_ring(full, (linked_dir / "c3/expected-high.bin").read_bytes(),
                                  out / "ring-budget", pcm["duration_s"])
    result["budget"] = measure_budget(Path(full["program"]), full["symbols"],
                                      pcm["frame_sample_counts_exact"], out / "budget")

    def capture_audio(item):
        name, (build, _, _) = item
        captured = support.capture(build, out / "programs" / name / "audio", pcm["duration_s"], audio=True)
        signal, rate = support.audio_signal(captured, native[name], pcm)
        support.save(out / "programs" / name / "audio-receipt.json", captured)
        return name, (signal, rate)

    with ThreadPoolExecutor(max_workers=3) as pool:
        signals = dict(pool.map(capture_audio, variants.items()))
    peak = max(float(np.max(np.abs(signal))) for name, (signal, _) in signals.items() if name != "muted")
    gain = 8.0 if peak * 8 < 1 else .92 / peak
    audio = {}
    for name, (signal, rate) in signals.items():
        if name == "muted":
            continue
        filename = f"{name}.wav"
        sf.write(out / filename, signal * gain, rate, subtype="PCM_16")
        audio[name] = {"file": filename, "sha256": support.digest(out / filename),
                       "frames": len(signal), "sample_rate": rate, "listening_gain": gain,
                       "peak": float(np.max(np.abs(signal * gain))),
                       "processing": "Native VICE capture, sample-clock crop, DC removal, one shared constant gain. No host mixing, EQ, alignment or dynamics."}
        if name in APPROVED_WAV:
            audio[name]["approved_reference_sha256"] = APPROVED_WAV[name]
            audio[name]["byte_identical_to_approved_wav"] = audio[name]["sha256"] == APPROVED_WAV[name]
            audio[name]["reference_comparison_at_gain8"] = reference_comparison(name, signal, rate)
    result["audio"] = audio
    muted = signals["muted"][0]
    result["muted"] = {"rms": float(np.std(muted)), "peak": float(np.max(np.abs(muted))),
                        "file_published": False}
    control = static_control(variants["muted"][0], out / "static-control")
    control_capture = support.capture(control, out / "static-control/audio", pcm["duration_s"], audio=True)
    static_signal, _ = support.audio_signal(control_capture, native["muted"], pcm)
    same_floor = np.array_equal(muted, static_signal)
    result["muted"].update(
        static_sid_waveform_identical=same_floor,
        static_control_program_sha256=control["program_sha256"],
        maximum_difference_pcm16_lsb=float(np.max(np.abs(muted - static_signal))) * 32768,
        scope="All-muted native performance compared with independently static SID after identical startup. No listening-file noise removal.")
    if not same_floor:
        support.save(out / "muted-check.json", result["muted"])
        raise ValueError("All-muted output differs from the static-SID control")
    support.save(out / "stems-check.json", {"variants": result["variants"], "audio": audio})
    support.save(out / "audio-check.json", {"audio": audio, "muted": result["muted"]})
    support.save(out / "verification.json", result)
    return result
