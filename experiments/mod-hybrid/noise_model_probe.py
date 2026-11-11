"""Diagnose four-PCM quantization noise without changing the player or model.

Capture the validated arithmetic model's pre-quantizer integer mixture at its
return boundary. Compare the emitted residual-feedback stream against ordinary
nearest-level rounding, with the same score, gain, cursor history and timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.signal import welch
import soundfile as sf

from pcm4_reference import PCM_RATE, expected_dac


HERE = Path(__file__).resolve().parent
ZOH_FACTOR = 16
ZOH_RATE = round(PCM_RATE * ZOH_FACTOR)
BANDS = (("0_to_500_hz", 0, 500), ("500_to_1500_hz", 500, 1500),
         ("1500_to_2000_hz", 1500, 2000), ("2000_to_20000_hz", 2000, 20000),
         ("all_to_20000_hz", 0, 20000))


def model_with_mixture(arrangement: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    captured = {}

    def profile(frame, event, arg):
        if event == "return" and frame.f_code is expected_dac.__code__:
            captured["mixed"] = frame.f_locals["mixed"].copy()

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        dac, receipt = expected_dac(arrangement)
    finally:
        sys.setprofile(previous)
    return dac, captured["mixed"], receipt


def zoh(values: np.ndarray) -> np.ndarray:
    return np.repeat(np.asarray(values, dtype=np.float32), ZOH_FACTOR)


def powers(values: np.ndarray) -> dict:
    held = zoh(values)
    held -= held.mean()
    frequencies, density = welch(held, fs=ZOH_RATE, nperseg=8192, noverlap=4096,
                                 scaling="density", detrend=False)
    step = frequencies[1] - frequencies[0]
    bands = {name: float(density[(frequencies >= low) & (frequencies < high)].sum() * step)
             for name, low, high in BANDS}
    return {"ac_rms_dac_lsb": float(np.sqrt(np.mean(held * held))),
            "mean_dac_lsb": float(np.mean(values)), "power_dac_lsb_squared": bands}


def snr(signal_power: float, error_power: float) -> float | None:
    if signal_power <= 0 or error_power <= 0:
        return None
    return float(10 * np.log10(signal_power / error_power))


def feedback_quantize(mixture: np.ndarray, initial_residual: int = 0) -> np.ndarray:
    cumulative = np.cumsum(mixture, dtype=np.int64) + initial_residual
    quotients = cumulative >> 4
    return np.diff(np.r_[np.int64(initial_residual >> 4), quotients])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "results/pcm4/short/arrangement.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4/noise-diagnosis-model")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    raw = args.input.read_bytes()
    arrangement = json.loads(raw)
    dac, mixed, model = model_with_mixture(arrangement)
    reference_path = HERE / "results/pcm4/reference/short/expected-DAC.bin"
    if dac.tobytes() != reference_path.read_bytes():
        raise ValueError("Noise diagnosis changed the validated current DAC bytes")
    ideal = np.empty(len(dac), dtype=np.float64)
    ideal[0] = 8
    ideal[1:] = mixed[:-1] / 16
    nearest = np.empty(len(dac), dtype=np.float64)
    nearest[0] = 8
    nearest[1:] = np.clip(np.rint(mixed[:-1] / 16), 0, 15)
    begin, end = round(30 * PCM_RATE), round(50 * PCM_RATE)
    ideal = ideal[begin:end] - 8
    feedback = dac[begin:end].astype(np.float64) - 8
    nearest = nearest[begin:end] - 8
    feedback_error = feedback - ideal
    nearest_error = nearest - ideal
    signals = {"pre_quantized_mix": ideal, "current_feedback": feedback,
               "feedback_off_nearest": nearest, "current_quantizer_error": feedback_error,
               "nearest_quantizer_error": nearest_error}
    measures = {name: powers(values) for name, values in signals.items()}
    comparisons = {}
    for name in ("current_quantizer_error", "nearest_quantizer_error"):
        comparisons[name] = {
            band: {"signal_power": measures["pre_quantized_mix"]["power_dac_lsb_squared"][band],
                   "error_power": measures[name]["power_dac_lsb_squared"][band],
                   "signal_to_error_db": snr(measures["pre_quantized_mix"]["power_dac_lsb_squared"][band],
                                              measures[name]["power_dac_lsb_squared"][band])}
            for band, _, _ in BANDS}
    # Keep the same one fixed gain for all audible variants. This exposes the
    # noise floor instead of independently boosting a quieter control.
    maximum = max(float(np.max(np.abs(values))) for values in (ideal, feedback, nearest))
    listening_gain = 0.85 / max(maximum, 1e-10)
    for name, values in signals.items():
        sf.write(args.out / f"{name}.wav", zoh(values) * listening_gain, ZOH_RATE, subtype="PCM_16")
        np.asarray(values, dtype="<f4").tofile(args.out / f"{name}-dac-lsb.f32")
    # True digital silence is mixed128, exactly representable as DAC8. Nearby
    # constants expose deterministic pulse trains from residual accumulation.
    constant_controls = []
    for residual in (0, 7, 15):
        output = feedback_quantize(np.full(4096, 128), residual)
        constant_controls.append({"mixture": 128, "initial_residual": residual,
                                  "output_values": sorted(set(map(int, output))),
                                  "zero_input_limit_cycle": bool(np.any(output != 8))})
    quiet_constants = []
    for offset in (1, 2, 4, 8):
        output = feedback_quantize(np.full(4096, 128 + offset)) - 8
        period = 16 // np.gcd(offset, 16)
        quiet_constants.append({"mixture_offset_from_silence": offset,
                                "ideal_dac_offset": offset / 16,
                                "output_values_relative_to_dac8": sorted(set(map(int, output))),
                                "repeat_period_samples": int(period), "repeat_frequency_hz": PCM_RATE / period,
                                "noise_ac_rms_dac_lsb": float(np.std(output)),
                                "nearest_constant_output_relative_to_dac8": int(np.rint((128 + offset) / 16)) - 8})
    high_band = "1500_to_2000_hz"
    old = measures["current_quantizer_error"]["power_dac_lsb_squared"][high_band]
    new = measures["nearest_quantizer_error"]["power_dac_lsb_squared"][high_band]
    receipt = {"arrangement": str(args.input.resolve()), "arrangement_sha256": hashlib.sha256(raw).hexdigest(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "validated_reference": str(reference_path.resolve()), "all_current_dac_bytes_reproduced": True,
               "passage_start_s": 30, "passage_end_s": 50, "dac_frames": len(ideal), "dac_rate_hz": PCM_RATE,
               "mix_min_max_before_quantization": [int(mixed.min()), int(mixed.max())],
               "measurements": measures, "signal_to_error": comparisons,
               "feedback_vs_nearest_error_power_ratio_1500_to_2000_hz": old / max(new, 1e-20),
               "zero_input_controls": constant_controls, "quiet_constant_controls": quiet_constants,
               "wav_rate": ZOH_RATE, "common_listening_gain": listening_gain,
               "wav_method": "Ideal DAC zero-order hold at16samples per DAC period (61578Hz), with a common fixed gain. No analog filtering, SID DAC nonlinearities, CPU jitter, independent gain matching, or host instrument mixing.",
               "power_method": "AC Welch power density on16x zero-order-held DAC samples, nperseg8192,50% overlap. Power bands integrate density; units DAC LSB squared. Images above2k are retained through20k.",
               "scope": "Arithmetic noise diagnosis only. Feedback-off can reduce high-frequency error while increasing correlated quantization distortion and suppressing quiet material. User listening determines preferred tradeoff."}
    (args.out / "noise-model.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"signal_to_error": comparisons,
                      "feedback_vs_nearest_error_power_ratio_1500_to_2000_hz": receipt["feedback_vs_nearest_error_power_ratio_1500_to_2000_hz"],
                      "zero_input_controls": constant_controls, "quiet_constant_controls": quiet_constants}, indent=2), flush=True)


if __name__ == "__main__":
    main()
