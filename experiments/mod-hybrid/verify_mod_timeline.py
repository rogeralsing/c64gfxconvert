"""Check complete MOD row flow against libopenmpt and render original audio.

The independent decoder runs to its own end, rather than being stepped using
the converter's tick schedule. Position observations are bounded to one audio
millisecond. The comparison checks row order, pattern, speed, declared tempo
and each row's elapsed time. It does not establish effect-pitch or C64 fidelity.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import ctypes.util
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from mod_reader import load_mod
from timeline import build_timeline

RATE = 192000
OUTPUT_RATE = 22050
OBSERVATION_FRAMES = 192
# The PAL Amiga CIA timer's tick quantization is distinct from output-frame
# quantization. Each source tick may differ from ideal 2.5/BPM by one CIA clock.
AMIGA_CIA_HZ = 709378.92


class Decoder:
    """Small binding to the installed libopenmpt C API, without a second replay."""

    def __init__(self, source: Path):
        self.library = ctypes.util.find_library("openmpt") or "/opt/homebrew/lib/libopenmpt.dylib"
        self.lib = ct.CDLL(self.library)
        self.lib.openmpt_module_create_from_memory2.restype = ct.c_void_p
        self.lib.openmpt_module_create_from_memory2.argtypes = [
            ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_void_p, ct.c_void_p,
            ct.c_void_p, ct.POINTER(ct.c_int), ct.c_void_p, ct.c_void_p,
        ]
        self.lib.openmpt_module_destroy.argtypes = [ct.c_void_p]
        self.lib.openmpt_module_get_duration_seconds.argtypes = [ct.c_void_p]
        self.lib.openmpt_module_get_duration_seconds.restype = ct.c_double
        self.lib.openmpt_module_set_repeat_count.argtypes = [ct.c_void_p, ct.c_int32]
        self.lib.openmpt_module_read_mono.argtypes = [
            ct.c_void_p, ct.c_int32, ct.c_size_t, ct.POINTER(ct.c_int16),
        ]
        self.lib.openmpt_module_read_mono.restype = ct.c_size_t
        self.lib.openmpt_module_ctl_set.argtypes = [ct.c_void_p, ct.c_char_p, ct.c_char_p]
        self.lib.openmpt_module_ctl_set.restype = ct.c_int
        self.lib.openmpt_module_set_render_param.argtypes = [ct.c_void_p, ct.c_int, ct.c_int32]
        self.lib.openmpt_module_set_render_param.restype = ct.c_int
        self.getters = {}
        for name in ("order", "row", "pattern", "speed"):
            function = getattr(self.lib, f"openmpt_module_get_current_{name}")
            function.argtypes = [ct.c_void_p]
            function.restype = ct.c_int32
            self.getters[name] = function
        tempo = self.lib.openmpt_module_get_current_tempo2
        tempo.argtypes = [ct.c_void_p]
        tempo.restype = ct.c_double
        self.getters["bpm"] = tempo
        raw = source.read_bytes()
        self.buffer = ct.create_string_buffer(raw)
        error = ct.c_int()
        self.handle = self.lib.openmpt_module_create_from_memory2(
            self.buffer, len(raw), None, None, None, None, ct.byref(error), None, None)
        if not self.handle:
            raise RuntimeError(f"libopenmpt failed to open {source.name}: error {error.value}")
        try:
            self.duration = self.lib.openmpt_module_get_duration_seconds(self.handle)
            self.lib.openmpt_module_set_repeat_count(self.handle, 0)
            for key, value in ((b"play.at_end", b"stop"),
                               (b"render.resampler.emulate_amiga", b"0"),
                               (b"dither", b"0")):
                if not self.lib.openmpt_module_ctl_set(self.handle, key, value):
                    raise RuntimeError(f"libopenmpt rejected control {key.decode()}")
            # Documented C API parameters: nearest sample interpolation and no
            # volume ramping make this a transparent original-sample reference.
            for key, value in ((3, 1), (4, 0)):
                if not self.lib.openmpt_module_set_render_param(self.handle, key, value):
                    raise RuntimeError(f"libopenmpt rejected render parameter {key}")
        except Exception:
            self.close()
            raise

    def state(self) -> dict:
        return {name: int(round(function(self.handle)))
                for name, function in self.getters.items()}

    def read(self, buffer: np.ndarray) -> int:
        return int(self.lib.openmpt_module_read_mono(
            self.handle, RATE, len(buffer), buffer.ctypes.data_as(ct.POINTER(ct.c_int16))))

    def close(self) -> None:
        if self.handle:
            self.lib.openmpt_module_destroy(self.handle)
            self.handle = None


def expected_rows(mod: dict, timeline: dict) -> list[dict]:
    result = []
    elapsed = 0.0
    for index, tick in enumerate(timeline["ticks"]):
        duration = float(tick["duration_s"])
        if duration <= 0 or not math.isfinite(duration):
            raise ValueError(f"Invalid timeline duration at tick {index}")
        if abs(float(tick["time_s"]) - elapsed) > 1e-6:
            raise ValueError(f"Timeline is not continuous at tick {index}")
        key = tuple(int(tick[name]) for name in ("order", "row", "pattern"))
        if not result or key != tuple(result[-1][name] for name in ("order", "row", "pattern")):
            bpm = int(tick["bpm"])
            result.append({"order": key[0], "row": key[1], "pattern": key[2],
                           "speed": int(tick["speed"]), "bpm": bpm,
                           "bpm_values": [bpm], "start_s": elapsed,
                           "duration_s": 0.0, "ticks": 0})
        # Fxx takes effect after tick zero. Compare the effective tempo values
        # throughout the row instead of requiring the initial getter to expose
        # the following tick's tempo prematurely.
        result[-1]["bpm"] = int(tick["bpm"])
        if result[-1]["bpm_values"][-1] != result[-1]["bpm"]:
            result[-1]["bpm_values"].append(result[-1]["bpm"])
        result[-1]["duration_s"] += duration
        result[-1]["ticks"] += 1
        elapsed += duration
    if abs(elapsed - float(timeline["duration_s"])) > 1e-6:
        raise ValueError("Timeline total duration differs from its tick durations")
    return result


def independent_rows(source: Path, seconds: float | None) -> tuple[list[dict], np.ndarray, dict]:
    decoder = Decoder(source)
    try:
        raw_source = source.read_bytes()
        duration = decoder.duration
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Independent decoder has no finite positive song duration")
        audio_duration = duration if seconds is None else min(seconds, duration)
        wanted_frames = round(audio_duration * RATE)
        pcm = bytearray()
        buffer = np.zeros(OBSERVATION_FRAMES, dtype=np.int16)
        transitions = []
        frames = 0
        pending_observation = None
        stop_frame = None
        termination = {"kind": "decoder_end"}
        limit = math.ceil((duration + 10) * RATE / OBSERVATION_FRAMES)
        for _ in range(limit):
            if stop_frame is not None and frames >= stop_frame:
                break
            view = buffer if stop_frame is None else buffer[:min(len(buffer), stop_frame - frames)]
            count = decoder.read(view)
            if not count:
                break
            # Defer each position observation until a following nonempty read.
            # The final read may have already reset the engine's position to
            # its restart order. Dropping only that terminal observation avoids
            # inventing a new audible row, even when the duration estimator and
            # the sample-quantized renderer have slightly different endpoints.
            if pending_observation is not None:
                lower, upper, state = pending_observation
                key = tuple(state[name] for name in ("order", "row", "pattern"))
                if not transitions or key != tuple(transitions[-1][name] for name in ("order", "row", "pattern")):
                    transitions.append({**state, "bpm_values": [state["bpm"]],
                                        "start_lower_s": lower, "start_upper_s": upper})
                    # PT2 stops on F00; libopenmpt intentionally ignores that
                    # command in some MODs. Identify it from the source bytes,
                    # independently of the converter's pattern reader, and use
                    # the independently observed row boundary plus one timer
                    # tick as the end convention used by this converter.
                    base = 1084 + state["pattern"] * 1024 + state["row"] * 16
                    stop_channels = [channel for channel in range(4)
                                     if raw_source[base + channel * 4 + 2] & 15 == 15
                                     and raw_source[base + channel * 4 + 3] == 0]
                    if stop_channels and stop_frame is None:
                        row_start = (lower + upper) / 2
                        stop_frame = round(row_start * RATE) + math.floor(RATE * 2.5 / state["bpm"])
                        termination = {"kind": "protracker_F00", "order": state["order"],
                                       "pattern": state["pattern"], "row": state["row"],
                                       "channels": stop_channels, "row_start_bound_s": [lower, upper],
                                       "stop_frame": stop_frame,
                                       "note": "F00 detected in raw MOD bytes. libopenmpt row observations validate flow through this PT2 stop command; its ignored-F00 tail is outside the source playback contract."}
                else:
                    transitions[-1]["bpm"] = state["bpm"]
                    if transitions[-1]["bpm_values"][-1] != state["bpm"]:
                        transitions[-1]["bpm_values"].append(state["bpm"])
            pending_observation = (frames / RATE, (frames + count) / RATE, decoder.state())
            keep = min(count, max(0, wanted_frames - len(pcm) // 2))
            if keep:
                pcm.extend(buffer[:keep].tobytes())
            frames += count
        else:
            raise ValueError("Independent decoder did not reach its own end within its duration bound")
        for index, row in enumerate(transitions):
            # Transition observations bound the actual boundary; use their
            # midpoint for readable measurements, retaining both endpoints.
            row["start_s"] = 0.0 if index == 0 else (row["start_lower_s"] + row["start_upper_s"]) / 2
        for index, row in enumerate(transitions):
            end = transitions[index + 1]["start_s"] if index + 1 < len(transitions) else frames / RATE
            row["duration_s"] = end - row["start_s"]
        actual_audio_duration = min(audio_duration, frames / RATE)
        wanted_frames = round(actual_audio_duration * RATE)
        if len(pcm) // 2 < wanted_frames:
            raise ValueError(f"Independent recording ended early: {len(pcm) // 2} of {wanted_frames} frames")
        native_pcm = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768
        reference = resample_poly(native_pcm, 147, 1280)
        reference = reference[:round(actual_audio_duration * OUTPUT_RATE)]
        reference = np.clip(np.rint(reference * 32768), -32768, 32767).astype(np.int16)
        return transitions, reference, {
            "library": decoder.library, "decoder_duration_s": frames / RATE,
            "decoder_estimated_duration_s": duration,
            "rendered_to_end_frames": frames, "rendered_to_end_s": frames / RATE,
            "observation_interval_s": OBSERVATION_FRAMES / RATE,
            "oracle_sample_rate": RATE, "original_sample_rate": OUTPUT_RATE,
            "audio_requested_s": actual_audio_duration, "termination": termination,
            "original_processing": "Independent decoder PCM at 192000 Hz, polyphase resampled 147/1280 to 22050 Hz. No gain, EQ or time alignment. High oracle rate bounds classic tracker tick truncation to one 192000-Hz output frame.",
            "render_settings": {"interpolation_filter_length": 1, "volume_ramping": 0,
                                "emulate_amiga_resampler": False, "dither": 0,
                                "repeat_count": 0, "play_at_end": "stop"}}
    finally:
        decoder.close()


def audio_comparison(mod: dict, timeline: dict, original: np.ndarray) -> dict:
    """Compare the custom note/effect states with independent sample audio.

    This deliberately keeps the native time axis and sample rate. Correlation
    is supplementary evidence: Paula/resampler phase differences can reduce it,
    so it is reported separately from the row-flow admission check.
    """
    from reference import render_timeline_pcm

    duration = len(original) / OUTPUT_RATE
    ticks = []
    for tick in timeline["ticks"]:
        if tick["time_s"] >= duration:
            break
        ticks.append({**tick, "duration_s": min(tick["duration_s"], duration - tick["time_s"])})
    rendered = render_timeline_pcm(mod, {"ticks": ticks, "duration_s": duration}, OUTPUT_RATE)
    independent = original.astype(np.float64) / 32768

    def metrics(a: np.ndarray, b: np.ndarray) -> dict:
        a, b = a - a.mean(), b - b.mean()
        ea, eb = float(np.dot(a, a)), float(np.dot(b, b))
        if min(ea, eb) < 1e-12:
            return {"waveform_correlation": None, "gain_aligned_normalized_rmse": None,
                    "independent_rms": float(np.sqrt(ea / len(a))),
                    "timeline_rms": float(np.sqrt(eb / len(b)))}
        cross = float(np.dot(a, b))
        gain = cross / eb
        return {"waveform_correlation": cross / math.sqrt(ea * eb),
                "gain_aligned_normalized_rmse": float(np.linalg.norm(a - gain * b) / math.sqrt(ea)),
                "analysis_gain": gain, "independent_rms": math.sqrt(ea / len(a)),
                "timeline_rms": math.sqrt(eb / len(b))}

    windows = []
    for start in range(0, len(original), 5 * OUTPUT_RATE):
        end = min(len(original), start + 5 * OUTPUT_RATE)
        windows.append({"start_s": start / OUTPUT_RATE, "duration_s": (end - start) / OUTPUT_RATE,
                        **metrics(independent[start:end], rendered[start:end])})
    frame = OUTPUT_RATE // 50
    end = len(original) // frame * frame
    envelope_a = np.sqrt(np.mean(independent[:end].reshape(-1, frame) ** 2, axis=1))
    envelope_b = np.sqrt(np.mean(rendered[:end].reshape(-1, frame) ** 2, axis=1))
    envelope_correlation = (float(np.corrcoef(envelope_a, envelope_b)[0, 1])
                            if min(float(envelope_a.std()), float(envelope_b.std())) > 1e-10 else None)
    return {"scope_s": duration, **metrics(independent, rendered),
            "twenty_ms_rms_envelope_correlation": envelope_correlation, "windows": windows,
            "method": "Original samples replayed from custom timeline versus independent libopenmpt nearest/no-ramp PCM. Native time axis; no shifting, warping, filtering or rewritten listening audio. A single fitted analysis gain reports mixer-scale differences.",
            "admission": "Diagnostic only; row-flow pass does not claim effect-pitch or sample-cursor equivalence."}


def verify_timeline(source: Path, out: Path, seconds: float | None = None) -> dict:
    """Validate the complete timeline and save a separate original-audio clip.

    ``seconds`` limits only the saved original WAV. The independent decoder
    still runs through the complete song and every observed row is compared.
    A failed check writes its diagnostic receipt before raising ValueError.
    """
    if seconds is not None and (not math.isfinite(seconds) or seconds <= 0):
        raise ValueError("seconds must be finite and positive")
    source, out = source.resolve(), out.resolve()
    mod = load_mod(source)
    timeline = build_timeline(mod)
    expected = expected_rows(mod, timeline)
    out.mkdir(parents=True, exist_ok=True)
    verifier_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    reference_hash = hashlib.sha256(Path(__file__).with_name("reference.py").read_bytes()).hexdigest()
    timeline_hash = hashlib.sha256(json.dumps(timeline, separators=(",", ":")).encode()).hexdigest()
    library = ctypes.util.find_library("openmpt") or "/opt/homebrew/lib/libopenmpt.dylib"
    library_hash = hashlib.sha256(Path(library).read_bytes()).hexdigest()
    decoder_identity = {"source_sha256": mod["sha256"], "verifier_sha256": verifier_hash,
                        "library_sha256": library_hash, "requested_seconds": seconds}
    identity = {**decoder_identity, "timeline_sha256": timeline_hash,
                "reference_renderer_sha256": reference_hash}
    wav = out / "original.wav"
    rows_path = out / "row-transitions.json"
    receipt_path = out / "timeline-check.json"
    cache_path = out / "independent-capture.json"
    cached = None
    if cache_path.exists() and rows_path.exists() and wav.exists():
        candidate = json.loads(cache_path.read_text())
        if (candidate.get("identity") == decoder_identity
                and candidate.get("rows_sha256") == hashlib.sha256(rows_path.read_bytes()).hexdigest()
                and candidate.get("wav_sha256") == hashlib.sha256(wav.read_bytes()).hexdigest()):
            cached = candidate
    if cached is not None:
        if receipt_path.exists():
            previous = json.loads(receipt_path.read_text())
            if previous.get("identity") == identity:
                if not previous["pass"]:
                    raise ValueError(f"Independent timeline mismatch; inspect {receipt_path}")
                return previous
        actual = json.loads(rows_path.read_text())
        original, cached_rate = sf.read(wav, dtype="int16")
        if cached_rate != OUTPUT_RATE or original.ndim != 1:
            raise ValueError("Cached independent recording has an unexpected format")
        independent = cached["independent"]
    else:
        actual, original, independent = independent_rows(source, seconds)
        sf.write(wav, original, OUTPUT_RATE, subtype="PCM_16")
        rows_path.write_text(json.dumps(actual, indent=2) + "\n")
        cache_path.write_text(json.dumps({"identity": decoder_identity, "independent": independent,
            "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
            "wav_sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}, indent=2) + "\n")
    mismatches = []
    max_row_error = 0.0
    fields = ("order", "row", "pattern", "speed", "bpm", "bpm_values")
    quantum = OBSERVATION_FRAMES / RATE
    for index, (wanted, observed) in enumerate(itertools.zip_longest(expected, actual)):
        if wanted is None or observed is None:
            mismatches.append({"row_index": index, "reason": "row_count", "expected": wanted, "actual": observed})
            continue
        differing = [field for field in fields if wanted[field] != observed[field]]
        if differing:
            mismatches.append({"row_index": index, "reason": "row_state", "fields": differing,
                               "expected": wanted, "actual": observed})
            continue
        error = observed["duration_s"] - wanted["duration_s"]
        max_row_error = max(max_row_error, abs(error))
        # Two sampled boundaries plus one output-frame/CIA timer quantum per
        # tick form an explicit bound. No audio alignment or tempo scaling is
        # performed, and the row sequence and state fields must match exactly.
        tolerance = 2 * quantum + wanted["ticks"] * (1 / RATE + 1 / AMIGA_CIA_HZ)
        if abs(error) > tolerance:
            mismatches.append({"row_index": index, "reason": "row_duration",
                               "error_s": error, "tolerance_s": tolerance,
                               "expected": wanted, "actual": observed})
    total_error = independent["decoder_duration_s"] - timeline["duration_s"]
    total_tolerance = 2 * quantum + len(timeline["ticks"]) * (1 / RATE + 1 / AMIGA_CIA_HZ)
    duration_pass = abs(total_error) <= total_tolerance
    receipt = {
        "pass": not mismatches and duration_pass, "identity": identity,
        "source": str(source), "source_sha256": mod["sha256"],
        "source_bytes": mod["bytes"], "decoder": "libopenmpt", **independent,
        "timeline_duration_s": timeline["duration_s"],
        "duration_error_s": total_error, "duration_tolerance_s": total_tolerance,
        "duration_pass": duration_pass, "timeline_ticks": len(timeline["ticks"]),
        "expected_row_segments": len(expected), "observed_row_segments": len(actual),
        "mismatch_count": len(mismatches), "mismatch_examples": mismatches[:32],
        "max_matching_row_duration_error_s": max_row_error,
        "row_states_sha256": hashlib.sha256(json.dumps(
            [[row[field] for field in fields] for row in actual], separators=(",", ":")).encode()).hexdigest(),
        "wav": {"file": str(wav), "sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
                "sample_rate": OUTPUT_RATE, "frames": len(original), "duration_s": len(original) / OUTPUT_RATE,
                "peak": int(np.max(np.abs(original.astype(np.int32))))},
        "audio_comparison": audio_comparison(mod, timeline, original),
        "timing_bound": "Per row: two observation intervals plus one output-frame and one PAL Amiga CIA clock per source tick. No signal alignment or time scaling.",
        "scope": "Complete independent row flow, pattern, speed, declared BPM and row-duration comparison. Separate original-sample audio from libopenmpt. Does not prove effect pitch, instrument cursor semantics or C64/DAC execution.",
        "references": ["https://lib.openmpt.org/doc/libopenmpt_8h.html",
                       "https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_replayer.c"],
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    if not receipt["pass"]:
        raise ValueError(f"Independent timeline mismatch; inspect {out / 'timeline-check.json'}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    receipt = verify_timeline(args.source, args.out, args.seconds)
    print(json.dumps({key: receipt[key] for key in (
        "pass", "timeline_duration_s", "decoder_duration_s", "timeline_ticks",
        "expected_row_segments", "mismatch_count", "max_matching_row_duration_error_s", "wav")}, indent=2))


if __name__ == "__main__":
    main()
