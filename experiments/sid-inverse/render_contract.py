"""Check PAL register tuning and actual PCM frequency against independent values.

This protects clock/register units at the renderer boundary. Synthetic recovery
cannot detect a shared tuning error in its own target generator. No test-only
renderer API is introduced.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sid_render import patch_events, render_patch


def main() -> None:
    patch = {"waveform": "triangle", "filter_mode": "off", "attack": 0,
             "decay": 0, "sustain": 15, "release": 0, "gate_s": 0.28,
             "pitch_start_semitones": 0, "pitch_end_semitones": 0, "attack_noise_s": 0}
    initial = {}
    for _, register, value in patch_events(patch, 0.3, 440, 200):
        initial.setdefault(register, value)
    # PAL 985248 Hz and the 24-bit accumulator give register $1d45 for A4.
    expected_register = 0x1D45
    actual_register = initial[0] | initial[1] << 8
    expected_hz = expected_register * 985248 / 16777216
    rows = []
    for model in ("6581", "8580"):
        samples = render_patch(patch, 0.3, 22050, model, 440, 200)[1000:5000]
        samples -= samples.mean()
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)), 262144))
        frequencies = np.fft.rfftfreq(262144, 1 / 22050)
        indexes = np.flatnonzero((frequencies > 400) & (frequencies < 480))
        measured = float(frequencies[indexes[np.argmax(spectrum[indexes])]])
        rows.append({"model": model, "expected_register": expected_register,
                     "actual_register": actual_register, "expected_hz": expected_hz,
                     "measured_hz": measured, "within_one_hz": abs(measured - expected_hz) < 1,
                     "rms": float(np.sqrt(np.mean(samples * samples)))})
    receipt = {"contract": "Independent PAL A4 register value and FFT fundamental on rendered PCM",
               "patch": patch, "results": rows}
    output = Path(__file__).resolve().parent / "results/render-contract.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(rows))
    if actual_register != expected_register or not all(row["within_one_hz"] and row["rms"] > 0.001 for row in rows):
        raise SystemExit("PAL tuning contract failed")


if __name__ == "__main__":
    main()
