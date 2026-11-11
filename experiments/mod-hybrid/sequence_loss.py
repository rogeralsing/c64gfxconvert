"""Score a complete, clock-aligned monophonic musical passage.

Features retain absolute frequency and time. Octaves are never folded together;
no candidate-specific time shift, time warp, frequency shift, onset trimming or
per-note gain is allowed. A single bounded gain compensates recording level.

This objective is a search aid, not a claim that a numeric score proves musical
or perceptual similarity. Final candidates still need the original/C64 audition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import resample_poly, stft
from scipy.sparse import csr_matrix


class SequenceLoss:
    """Compare equally timed audio against a fixed complete target passage.

    ``target`` and every ``measure(audio)`` input use the constructor's sample
    rate. Analysis uses at most 11025 Hz. For repeated calls, supplying 11025 Hz
    input avoids resampling work. Short inputs are zero-padded and penalized;
    long inputs are truncated and penalized. No content alignment is performed.
    """

    def __init__(self, target: np.ndarray, sample_rate: int):
        self.sample_rate = int(sample_rate)
        if self.sample_rate < 8000:
            raise ValueError("Sequence loss requires at least 8000 Hz input")
        self.analysis_rate = min(11025, self.sample_rate)
        raw = self._validate(target)
        self.input_length = len(raw)
        self.target = self._resample(raw)
        self.length = len(self.target)
        self.fft_sizes = (256, 1024, 4096)
        self.hop = round(self.analysis_rate * 0.02)
        self.envelope_hop = round(self.analysis_rate * 0.01)
        self.target_envelope = self._envelope(self.target)
        self.envelope_floor = max(float(np.max(self.target_envelope)) * 0.005, 1e-8)
        if float(np.max(self.target_envelope)) < 1e-7:
            raise ValueError("Target passage is silent")
        self.target_onset = np.maximum(0, np.diff(self.target_envelope))
        self.target_offset = np.maximum(0, -np.diff(self.target_envelope))
        self.target_spectra = self._spectra(self.target)
        self.frame_weights = []
        self.spectral_floors = []
        for spectrum in self.target_spectra:
            energy = np.sqrt(np.sum(spectrum * spectrum, axis=0))
            active = energy >= max(float(energy.max()) * 0.005, 1e-10)
            # Fourth-root energy balancing stops the loudest transient from
            # erasing quieter notes from the score while suppressing silence.
            weights = np.where(active, np.maximum(energy, 1e-10) ** 0.25, 0)
            self.frame_weights.append(weights / max(float(weights.sum()), 1e-10))
            self.spectral_floors.append(max(float(spectrum.sum(axis=0).max()) * 0.01, 1e-10))
        self.log_min = math.log2(40.0)
        self.log_max = math.log2(self.analysis_rate / 2)
        self.log_band_count = math.ceil((self.log_max - self.log_min) * 36) + 1
        self.log_centres = np.linspace(self.log_min, self.log_max, self.log_band_count)
        self.log_step = float(self.log_centres[1] - self.log_centres[0])
        frequencies = np.fft.rfftfreq(self.fft_sizes[-1], 1 / self.analysis_rate)
        columns = np.flatnonzero(frequencies >= 40)
        positions = ((np.log2(frequencies[columns]) - self.log_min)
                     / (self.log_max - self.log_min) * (self.log_band_count - 1))
        lower = np.floor(positions).astype(int)
        upper = np.minimum(self.log_band_count - 1, lower + 1)
        weights = positions - lower
        self.log_filter = csr_matrix((np.r_[1 - weights, weights],
                                      (np.r_[lower, upper], np.r_[columns, columns])),
                                     shape=(self.log_band_count, len(frequencies)))
        self.target_log = self._log_distribution(self.target_spectra[-1])
        self.target_cdf = np.cumsum(self.target_log, axis=0)
        self.target_carrier = self.log_centres[np.argmax(self.target_log, axis=0)]
        peak_share = np.max(self.target_log, axis=0)
        # Compare concentration to the actual band count. A fixed probability
        # threshold would silently disable this component for broad, complex
        # original samples even when their strongest carrier is informative.
        tonal_confidence = np.clip((peak_share * self.log_band_count - 2) / 5, 0, 1)
        carrier_weights = self.frame_weights[-1] * tonal_confidence
        if float(carrier_weights.sum()) <= 1e-10:
            carrier_weights = self.frame_weights[-1]
        self.carrier_weights = carrier_weights / max(float(carrier_weights.sum()), 1e-10)

    @staticmethod
    def _validate(audio: np.ndarray) -> np.ndarray:
        array = np.asarray(audio, dtype=np.float32)
        if array.ndim != 1 or len(array) == 0 or not np.all(np.isfinite(array)):
            raise ValueError("Expected nonempty finite mono audio")
        return array

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        if self.analysis_rate == self.sample_rate:
            return audio
        divisor = math.gcd(self.analysis_rate, self.sample_rate)
        return resample_poly(audio, self.analysis_rate // divisor, self.sample_rate // divisor).astype(np.float32)

    def _spectra(self, audio: np.ndarray) -> list[np.ndarray]:
        return [np.abs(stft(audio, fs=self.analysis_rate, window="hann", nperseg=size,
                            noverlap=size - self.hop, boundary="zeros", padded=True)[2])
                for size in self.fft_sizes]

    def _envelope(self, audio: np.ndarray) -> np.ndarray:
        energy = uniform_filter1d(audio * audio, round(self.analysis_rate * 0.02), mode="constant")
        return np.sqrt(np.maximum(0, energy[::self.envelope_hop]))

    def _log_distribution(self, spectrum: np.ndarray) -> np.ndarray:
        bands = np.asarray(self.log_filter @ spectrum)
        # Interpolation across adjacent absolute-pitch bands tolerates tiny
        # emulator tuning differences without identifying different octaves.
        bands = uniform_filter1d(bands, 3, axis=0, mode="nearest")
        return bands / np.maximum(bands.sum(axis=0, keepdims=True), 1e-10)

    def measure(self, audio: np.ndarray) -> dict:
        raw = self._validate(audio)
        length_error = abs(len(raw) - self.input_length) / self.input_length
        raw = np.pad(raw[:self.input_length], (0, max(0, self.input_length - len(raw))))
        candidate = self._resample(raw)
        candidate = np.pad(candidate[:self.length], (0, max(0, self.length - len(candidate))))
        envelope = self._envelope(candidate)
        active = ((self.target_envelope > self.envelope_floor)
                  & (envelope > max(float(envelope.max()) * 0.005, 1e-10)))
        # A single robust level adjustment. Keeping it global preserves each
        # note's level, decay and attack relative to the rest of the phrase.
        gain = float(np.median(self.target_envelope[active] / np.maximum(envelope[active], 1e-10))) if active.any() else 1.0
        gain = min(32.0, max(1 / 32, gain))
        candidate = candidate * gain
        envelope = envelope * gain
        spectra = self._spectra(candidate)
        multires = []
        harmonic = []
        for target, actual, weights, floor in zip(self.target_spectra, spectra,
                                                  self.frame_weights, self.spectral_floors):
            denominator = np.maximum(target.sum(axis=0), floor)
            frame_error = np.minimum(5, np.abs(target - actual).sum(axis=0) / denominator)
            multires.append(float(np.sum(frame_error * weights)))
            dot = np.sum(target * actual, axis=0)
            norms = np.sqrt(np.sum(target * target, axis=0) * np.sum(actual * actual, axis=0))
            cosine = dot / np.maximum(norms, 1e-12)
            harmonic.append(float(np.sum((1 - np.clip(cosine, 0, 1)) * weights)))
        distribution = self._log_distribution(spectra[-1])
        register_per_frame = (np.sum(np.abs(self.target_cdf - np.cumsum(distribution, axis=0)), axis=0)
                              * self.log_step)
        absolute_register = float(np.sum(np.minimum(4, register_per_frame) * self.frame_weights[-1]))
        carrier = self.log_centres[np.argmax(distribution, axis=0)]
        carrier_pitch = float(np.sum(np.minimum(4, np.abs(carrier - self.target_carrier)) * self.carrier_weights))
        envelope_error = float(np.mean(np.abs(envelope - self.target_envelope))
                               / (np.mean(self.target_envelope) + self.envelope_floor))
        difference = np.diff(envelope)
        onset = float(np.mean(np.abs(np.maximum(0, difference) - self.target_onset))
                      / (np.mean(self.target_onset) + self.envelope_floor * 0.1))
        offset = float(np.mean(np.abs(np.maximum(0, -difference) - self.target_offset))
                       / (np.mean(self.target_offset) + self.envelope_floor * 0.1))
        spectral = float(np.mean(multires))
        harmonic_shape = float(np.mean(harmonic))
        silence_penalty = 5.0 if float(np.max(np.abs(candidate))) < 1e-7 else 0.0
        loss = (0.20 * spectral + 0.15 * harmonic_shape + 0.25 * absolute_register
                + 0.15 * carrier_pitch + 0.15 * envelope_error + 0.07 * onset
                + 0.03 * offset + length_error + silence_penalty)
        return {"loss": loss, "spectral": spectral, "harmonic_shape": harmonic_shape,
                "absolute_register": absolute_register, "carrier_pitch": carrier_pitch,
                "envelope": envelope_error, "onset": onset, "offset": offset,
                "length_error": length_error, "silence_penalty": silence_penalty,
                "global_gain": gain, "analysis_rate": self.analysis_rate,
                "pitch_distance_unit": "octaves on an absolute frequency axis; no pitch-class folding"}


def _pitch_control(audio: np.ndarray, rate: int, semitones: int) -> np.ndarray:
    """External FFmpeg pitch control, retaining duration through atempo."""
    factor = 2 ** (semitones / 12)
    tempo = 1 / factor
    stages = []
    while tempo < 0.5:
        stages.append("atempo=0.5")
        tempo *= 2
    while tempo > 2:
        stages.append("atempo=2")
        tempo /= 2
    stages.append(f"atempo={tempo:.12f}")
    filters = [f"asetrate={rate * factor:.12f}", *stages, f"aresample={rate}"]
    completed = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "f32le",
                                "-ar", str(rate), "-ac", "1", "-i", "pipe:0", "-af", ",".join(filters),
                                "-f", "f32le", "-ar", str(rate), "-ac", "1", "pipe:1"],
                               input=np.asarray(audio, dtype="<f4").tobytes(), capture_output=True, timeout=30)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode())
    result = np.frombuffer(completed.stdout, dtype="<f4")
    return np.pad(result[:len(audio)], (0, max(0, len(audio) - len(result))))


def main() -> None:
    import soundfile as sf

    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=here / "results/channel-solos/original/track-2.wav")
    parser.add_argument("--candidate", type=Path, default=here / "results/channel-solos/c64/track-2/vice/stardust-vice.wav")
    parser.add_argument("--out", type=Path, default=here / "results/channel-fit-2/loss-diagnosis.json")
    args = parser.parse_args()
    target, rate = sf.read(args.target, dtype="float32")
    # The actual VICE solo begins at song time zero. The independent original
    # solo is already the selected 30–50 s passage.
    candidate, candidate_rate = sf.read(args.candidate, dtype="float32", start=30 * rate, stop=50 * rate)
    if candidate_rate != rate:
        raise ValueError("Baseline and target rates differ")
    started = time.perf_counter()
    objective = SequenceLoss(target, rate)
    setup_seconds = time.perf_counter() - started
    rng = np.random.default_rng(418)
    controls = {"identity": target, "level_only_half": target * 0.5,
                "near_identity_small_noise": target + rng.normal(0, 1e-4, len(target)),
                "delay_250ms": np.pad(target[:-round(rate * 0.25)], (round(rate * 0.25), 0)),
                "silence": np.zeros_like(target), "actual_v2_c64_solo": candidate}
    analysis_target = resample_poly(target, 1, 2)
    for semitones in (7, 12, -12, 48):
        controls[f"pitch_{semitones:+d}_semitones"] = resample_poly(_pitch_control(analysis_target, rate // 2, semitones), 2, 1)[:len(target)]
    scores = {}
    timings = []
    for name, audio in controls.items():
        begin = time.perf_counter()
        scores[name] = objective.measure(audio)
        timings.append(time.perf_counter() - begin)
    near = scores["near_identity_small_noise"]["loss"]
    checks = {
        "identity_is_zero": scores["identity"]["loss"] < 1e-5,
        "global_gain_invariant": scores["level_only_half"]["loss"] < 1e-5,
        "near_identity_better_than_pitch_timing_and_silence": all(
            near < scores[name]["loss"] for name in scores
            if name.startswith("pitch_") or name in ("delay_250ms", "silence")),
        "octaves_are_penalized_on_absolute_frequency_axis": all(
            scores[name]["absolute_register"] > 0.2 for name in ("pitch_+12_semitones", "pitch_-12_semitones", "pitch_+48_semitones")),
        "carrier_component_detects_octave_controls": all(
            scores[name]["carrier_pitch"] > 0.1 for name in ("pitch_+12_semitones", "pitch_-12_semitones", "pitch_+48_semitones")),
        "delay_is_penalized_in_envelope": scores["delay_250ms"]["envelope"] > 0.1,
    }
    receipt = {"target": str(args.target.resolve()), "target_sha256": hashlib.sha256(args.target.read_bytes()).hexdigest(),
               "candidate": str(args.candidate.resolve()), "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "passage_start_s": 30, "passage_duration_s": len(target) / rate,
               "input_rate": rate, "analysis_rate": objective.analysis_rate,
               "setup_seconds": setup_seconds, "median_measure_seconds": float(np.median(timings)),
               "scores": scores, "checks": checks, "all_checks_pass": all(checks.values()),
               "alignment": "Fixed 30–50 s passage; no candidate-specific lag search, time warp, onset trimming or pitch adjustment.",
               "pitch_controls": "External FFmpeg asetrate plus duration-preserving atempo; these controls may introduce resampling/phase artifacts. Absolute-register and carrier components report octave errors separately from timing.",
               "validation_contract": "Preserve absolute pitch/register, complete passage timing, spectral/harmonic shape and relative note envelope. Negative controls independently alter known audible properties. They guard against octave folding, free alignment, silent solutions and peak-normalization shortcuts.",
               "scope": "An objective for a single original track's whole phrase. Numeric improvement does not establish listener recognition or prove general note identity."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"baseline": scores["actual_v2_c64_solo"], "setup_seconds": setup_seconds,
                      "median_measure_seconds": receipt["median_measure_seconds"], "checks": checks,
                      "control_losses": {name: score["loss"] for name, score in scores.items()}}, indent=2))
    if not all(checks.values()):
        raise SystemExit("Sequence objective failed a negative-control contract")


if __name__ == "__main__":
    main()
