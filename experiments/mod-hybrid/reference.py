"""Render the original MOD with independent libopenmpt and check score timing.

Requires libopenmpt (macOS: ``brew install libopenmpt``), numpy and soundfile.
This decoder never uses the experiment's synthetic instruments or PCM mixer.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import ctypes.util
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from mod_reader import load_mod
from timeline import build_timeline

PAULA_CLOCK = 3546894.6


def render_timeline_pcm(mod: dict, timeline: dict, rate: int) -> np.ndarray:
    """Render the score with its original samples, without SID approximations.

    Nearest-neighbour resampling and hard volume steps make replay semantics
    directly comparable with the independent decoder's matching control mode.
    """
    data = {s["id"]: np.frombuffer(s["data"], dtype=np.int8).astype(np.float64) / 128
            for s in mod["samples"]}
    output = np.zeros(round(timeline["duration_s"] * rate))
    positions = [0.0] * 4
    for tick in timeline["ticks"]:
        start = round(tick["time_s"] * rate)
        end = round((tick["time_s"] + tick["duration_s"]) * rate)
        frames = end - start
        for channel, state in enumerate(tick["channels"]):
            instrument, period = state["playing_sample"], state["period"]
            if state["trigger"]:
                positions[channel] = float(state["offset"])
            if not instrument or not period:
                continue
            sample = mod["samples"][instrument - 1]
            step = PAULA_CLOCK / period / rate
            sample_positions = positions[channel] + np.arange(frames) * step
            if sample["loop_length"] > 2:
                loop_end = sample["loop_start"] + sample["loop_length"]
                wrap = sample_positions >= loop_end
                sample_positions[wrap] = (sample["loop_start"]
                                          + (sample_positions[wrap] - sample["loop_start"]) % sample["loop_length"])
            indices = np.floor(sample_positions).astype(np.int64)
            valid = (indices >= 0) & (indices < len(data[instrument]))
            block = np.zeros(frames)
            block[valid] = data[instrument][indices[valid]]
            output[start:end] += block * state["volume"] / 64 / 4
            positions[channel] += frames * step
            if sample["loop_length"] > 2 and positions[channel] >= loop_end:
                positions[channel] = (sample["loop_start"]
                                      + (positions[channel] - sample["loop_start"]) % sample["loop_length"])
    return output


def _audio_metrics(expected: np.ndarray, actual: np.ndarray, rate: int) -> dict:
    expected = expected - expected.mean()
    actual = actual - actual.mean()
    denominator = float(np.dot(actual, actual))
    gain = float(np.dot(expected, actual) / denominator) if denominator else 0
    aligned = gain * actual
    error = expected - aligned
    _, _, a = signal.stft(expected, fs=rate, nperseg=1024, noverlap=768)
    _, _, b = signal.stft(aligned, fs=rate, nperseg=1024, noverlap=768)
    a, b = np.abs(a), np.abs(b)
    envelope_a = np.sqrt(np.mean(expected[:len(expected) // 441 * 441].reshape(-1, 441) ** 2, axis=1))
    envelope_b = np.sqrt(np.mean(aligned[:len(aligned) // 441 * 441].reshape(-1, 441) ** 2, axis=1))
    return {"waveform_correlation": float(np.corrcoef(expected, actual)[0, 1]),
            "least_squares_gain": gain,
            "gain_aligned_normalized_rmse": float(np.linalg.norm(error) / np.linalg.norm(expected)),
            "short_time_magnitude_spectral_error": float(np.linalg.norm(a - b) / np.linalg.norm(a)),
            "tick_rms_envelope_correlation": float(np.corrcoef(envelope_a, envelope_b)[0, 1])}


def validate_audio(source: Path, out: Path, rate: int = 22050) -> dict:
    """Compare complete rendered music, including effects, with a second decoder."""
    mod = load_mod(source)
    timeline = build_timeline(mod)
    out.mkdir(parents=True, exist_ok=True)
    control = out / "original-control.wav"
    command = ["openmpt123", "--batch", "--quiet", "--no-progress", "--no-details",
               "--samplerate", str(rate), "--channels", "1", "--no-float", "--filter", "1",
               "--ramping", "0", "--ctl", "render.resampler.emulate_amiga=0",
               "--ctl", "dither=0", "--repeat", "0", "--end-time", str(timeline["duration_s"]),
               "--output", str(control.resolve()), "--force", str(source.resolve())]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (out / "control-render.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(f"Independent control render failed: {completed.stderr}")
    independent, actual_rate = sf.read(control, dtype="float64")
    if actual_rate != rate or independent.ndim != 1:
        raise ValueError("Unexpected independent control output")
    expected = render_timeline_pcm(mod, timeline, rate)
    if len(independent) < len(expected):
        raise ValueError("Independent audio stopped before timeline")
    independent_file_frames = len(independent)
    independent = independent[:len(expected)]
    sf.write(out / "timeline-pcm.wav", expected, rate, subtype="PCM_16")
    sf.write(out / "timeline-pcm-preview.wav", expected[30 * rate:50 * rate], rate, subtype="PCM_16")
    metrics = _audio_metrics(independent, expected, rate)
    windows = []
    for start_s in range(0, int(timeline["duration_s"]), 20):
        start, end = start_s * rate, min(len(expected), (start_s + 20) * rate)
        windows.append({"start_s": start_s, "duration_s": (end - start) / rate,
                        **_audio_metrics(independent[start:end], expected[start:end], rate)})
    triggers = [sum(tick["channels"][channel]["trigger"] for tick in timeline["ticks"])
                for channel in range(4)]
    receipt = {"source_sha256": mod["sha256"], "frames": len(expected), "rate": rate,
               "independent_control_file_frames": independent_file_frames,
               "independent_trailing_frames_excluded": independent_file_frames - len(expected),
               "duration_s": len(expected) / rate, "full_song": metrics, "windows": windows,
               "control_render_command": command, "triggers_per_mod_track": triggers,
               "total_triggers": sum(triggers), "fixed_assignment": ["PCM1", "PCM2", "SID1", "SID2"],
               "assignment_trigger_capacity": "Each MOD track owns a physical voice. Simultaneous triggers on all four tracks fit without voice stealing.",
               "scope": "Audio comparison tests original PCM sample replay and effect semantics. It does not assess SID replacement timbres or prove hardware timing. Resampler, phase, mixer and filtering differences can remain."}
    (out / "audio-comparison.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def render_reference(source: Path, out: Path, rate: int = 22050) -> dict:
    mod = load_mod(source)
    timeline = build_timeline(mod)
    out.mkdir(parents=True, exist_ok=True)
    library = ctypes.util.find_library("openmpt") or "/opt/homebrew/lib/libopenmpt.dylib"
    lib = ct.CDLL(library)
    lib.openmpt_module_create_from_memory2.restype = ct.c_void_p
    lib.openmpt_module_create_from_memory2.argtypes = [
        ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_void_p, ct.c_void_p,
        ct.c_void_p, ct.POINTER(ct.c_int), ct.c_void_p, ct.c_void_p,
    ]
    lib.openmpt_module_destroy.argtypes = [ct.c_void_p]
    lib.openmpt_module_get_duration_seconds.argtypes = [ct.c_void_p]
    lib.openmpt_module_get_duration_seconds.restype = ct.c_double
    lib.openmpt_module_read_mono.argtypes = [ct.c_void_p, ct.c_int32, ct.c_size_t,
                                           ct.POINTER(ct.c_int16)]
    lib.openmpt_module_read_mono.restype = ct.c_size_t
    lib.openmpt_module_set_repeat_count.argtypes = [ct.c_void_p, ct.c_int32]
    getters = {}
    for name in ("order", "row", "speed", "pattern"):
        function = getattr(lib, f"openmpt_module_get_current_{name}")
        function.argtypes = [ct.c_void_p]
        function.restype = ct.c_int32
        getters[name] = function
    raw = source.read_bytes()
    buffer = ct.create_string_buffer(raw)
    error = ct.c_int(0)
    handle = lib.openmpt_module_create_from_memory2(buffer, len(raw), None, None,
                                                  None, None, ct.byref(error), None, None)
    if not handle:
        raise RuntimeError(f"libopenmpt failed to open module, error {error.value}")
    mismatch = []
    transitions = []
    blocks = []
    try:
        duration = lib.openmpt_module_get_duration_seconds(handle)
        lib.openmpt_module_set_repeat_count(handle, 0)
        expected_duration = timeline["duration_s"]
        if abs(duration - expected_duration) > 1 / rate:
            raise ValueError(f"Independent decoder duration differs: {duration} vs {expected_duration}")
        position = None
        for index, tick in enumerate(timeline["ticks"]):
            frames = round((tick["time_s"] + tick["duration_s"]) * rate) - round(tick["time_s"] * rate)
            pcm = np.zeros(frames, dtype=np.int16)
            count = lib.openmpt_module_read_mono(handle, rate, frames,
                                               pcm.ctypes.data_as(ct.POINTER(ct.c_int16)))
            if count != frames:
                raise ValueError(f"Independent decoder stopped early at tick {index}")
            blocks.append(pcm)
            actual = {name: function(handle) for name, function in getters.items()}
            expected = {name: tick[name] for name in getters}
            if actual != expected:
                mismatch.append({"tick_index": index, "time_s": tick["time_s"],
                                 "expected": expected, "actual": actual})
            current = (actual["order"], actual["row"])
            if current != position:
                transitions.append({"tick_index": index, "time_s": tick["time_s"], **actual})
                position = current
    finally:
        lib.openmpt_module_destroy(handle)
    pcm = np.concatenate(blocks)
    full = out / "original.wav"
    preview = out / "original-preview.wav"
    sf.write(full, pcm, rate, subtype="PCM_16")
    preview_start_s, preview_duration_s = 30, 20
    sf.write(preview, pcm[preview_start_s * rate:(preview_start_s + preview_duration_s) * rate],
             rate, subtype="PCM_16")
    version = subprocess.run(["openmpt123", "--short-version"], capture_output=True, text=True,
                             timeout=10)
    receipt = {
        "decoder": "libopenmpt", "decoder_version": version.stdout.strip(), "library": library,
        "source_sha256": mod["sha256"], "source_bytes": len(raw),
        "sample_rate": rate, "frames": len(pcm), "duration_s": len(pcm) / rate,
        "decoder_duration_s": duration, "timeline_duration_s": expected_duration,
        "ticks_checked": len(timeline["ticks"]), "rows_checked": len(timeline["rows"]),
        "comparison": "Independent decoder order, row, pattern and speed after each rendered tick",
        "mismatch_count": len(mismatch), "mismatch_examples": mismatch[:20],
        "effects_handled": timeline["effects_handled"], "termination": timeline["termination"],
        "peak": int(np.max(np.abs(pcm.astype(np.int32)))),
        "rms": float(np.sqrt(np.mean((pcm.astype(np.float64) / 32768) ** 2))),
        "wav_sha256": hashlib.sha256(full.read_bytes()).hexdigest(),
        "preview_start_s": preview_start_s, "preview_duration_s": preview_duration_s,
        "timing_note": "Original uses ideal 50 Hz libopenmpt ticks; physical PAL CIA timer quantization is a separate backend constraint.",
        "scope": "Checks whole-song score timing and independently renders original audio. Does not prove effect-pitch equivalence or SID timbre quality.",
        "references": [
            "https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_replayer.c",
            "https://lib.openmpt.org/doc/libopenmpt_8h.html",
        ],
    }
    (out / "row-transitions.json").write_text(json.dumps(transitions, indent=2) + "\n")
    (out / "reference.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if mismatch:
        raise ValueError(f"Independent decoder differs at {len(mismatch)} ticks; inspect reference.json")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=Path(__file__).parent / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results/reference")
    parser.add_argument("--check-audio", action="store_true",
                        help="Compare four-PCM timeline replay with an independent controlled decode")
    args = parser.parse_args()
    result = validate_audio(args.source, args.out) if args.check_audio else render_reference(args.source, args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
