"""Render the original MOD's four tracks separately using libopenmpt muting.

The decoder plays from the beginning to preserve note/sample/filter history.
It keeps the original reference's default pitch, tempo, gain and filters. Each
file contains the unscaled 30–50 s passage of exactly one original MOD track.
"""
from __future__ import annotations

import argparse
import ctypes as ct
from ctypes.util import find_library
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf


HERE = Path(__file__).resolve().parent


class Interactive(ct.Structure):
    """ABI from libopenmpt_ext.h's openmpt_module_ext_interface_interactive."""
    _fields_ = [(name, ct.c_void_p) for name in (
        "set_current_speed", "set_current_tempo", "set_tempo_factor", "get_tempo_factor",
        "set_pitch_factor", "get_pitch_factor", "set_global_volume", "get_global_volume",
        "set_channel_volume", "get_channel_volume", "set_channel_mute_status",
        "get_channel_mute_status", "set_instrument_mute_status", "get_instrument_mute_status",
        "play_note", "stop_note",
    )]


def load_library() -> tuple[ct.CDLL, str]:
    location = find_library("openmpt") or "/opt/homebrew/lib/libopenmpt.dylib"
    lib = ct.CDLL(location)
    lib.openmpt_module_ext_create_from_memory.argtypes = [
        ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_void_p, ct.c_void_p,
        ct.c_void_p, ct.POINTER(ct.c_int), ct.c_void_p, ct.c_void_p,
    ]
    lib.openmpt_module_ext_create_from_memory.restype = ct.c_void_p
    lib.openmpt_module_ext_destroy.argtypes = [ct.c_void_p]
    lib.openmpt_module_ext_get_module.argtypes = [ct.c_void_p]
    lib.openmpt_module_ext_get_module.restype = ct.c_void_p
    lib.openmpt_module_ext_get_interface.argtypes = [ct.c_void_p, ct.c_char_p, ct.c_void_p, ct.c_size_t]
    lib.openmpt_module_ext_get_interface.restype = ct.c_int
    lib.openmpt_module_read_mono.argtypes = [ct.c_void_p, ct.c_int32, ct.c_size_t, ct.POINTER(ct.c_int16)]
    lib.openmpt_module_read_mono.restype = ct.c_size_t
    lib.openmpt_module_get_num_channels.argtypes = [ct.c_void_p]
    lib.openmpt_module_get_num_channels.restype = ct.c_int32
    lib.openmpt_module_set_repeat_count.argtypes = [ct.c_void_p, ct.c_int32]
    lib.openmpt_module_set_repeat_count.restype = ct.c_int
    return lib, location


def render_track(lib: ct.CDLL, data: bytes, selected: int, rate: int, frames: int) -> tuple[np.ndarray, dict]:
    source = ct.create_string_buffer(data)
    error = ct.c_int(0)
    extended = lib.openmpt_module_ext_create_from_memory(source, len(data), None, None, None, None,
                                                       ct.byref(error), None, None)
    if not extended:
        raise RuntimeError(f"libopenmpt could not open MOD, error {error.value}")
    try:
        module = lib.openmpt_module_ext_get_module(extended)
        if lib.openmpt_module_get_num_channels(module) != 4:
            raise ValueError("Expected exactly four original MOD tracks")
        interface = Interactive()
        if lib.openmpt_module_ext_get_interface(extended, b"interactive", ct.byref(interface), ct.sizeof(interface)) != 1:
            raise RuntimeError("libopenmpt interactive channel-muting extension unavailable")
        set_mute = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_int32, ct.c_int)(interface.set_channel_mute_status)
        get_mute = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_int32)(interface.get_channel_mute_status)
        expected = [int(channel != selected) for channel in range(4)]
        for channel, mute in enumerate(expected):
            if set_mute(extended, channel, mute) != 1:
                raise RuntimeError(f"Could not set original MOD track {channel + 1} mute status")
        before = [get_mute(extended, channel) for channel in range(4)]
        if before != expected:
            raise ValueError("Independent decoder did not accept requested solo state")
        lib.openmpt_module_set_repeat_count(module, 0)
        pcm = np.empty(frames, dtype=np.int16)
        position = 0
        while position < frames:
            count = min(4096, frames - position)
            destination = pcm[position:position + count]
            decoded = lib.openmpt_module_read_mono(module, rate, count,
                                                  destination.ctypes.data_as(ct.POINTER(ct.c_int16)))
            if decoded != count:
                raise ValueError("Original decoder ended before requested passage")
            position += decoded
        after = [get_mute(extended, channel) for channel in range(4)]
        if after != expected:
            raise ValueError("Original decoder changed the solo mute state during playback")
        return pcm, {"mute_status_before": before, "mute_status_after": after}
    finally:
        lib.openmpt_module_ext_destroy(extended)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-solos/original")
    parser.add_argument("--reference", type=Path, default=HERE / "results/reference/original.wav")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rate, start_s, end_s = 22050, 30, 50
    raw = args.source.read_bytes()
    lib, location = load_library()
    solos, receipts = [], []
    for selected in range(4):
        full, mute_receipt = render_track(lib, raw, selected, rate, end_s * rate)
        pcm = full[start_s * rate:end_s * rate]
        path = args.out / f"track-{selected + 1}.wav"
        sf.write(path, pcm, rate, subtype="PCM_16")
        values = pcm.astype(np.float64) / 32768
        if not np.max(np.abs(values)):
            raise ValueError(f"Original track {selected + 1} unexpectedly silent")
        solos.append(values)
        receipts.append({"mod_track_1_based": selected + 1, "file": str(path.resolve()),
                         "frames": len(pcm), "sample_rate": rate, "duration_s": len(pcm) / rate,
                         "rms": float(np.sqrt(np.mean(values ** 2))), "peak": float(np.max(np.abs(values))),
                         "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **mute_receipt})
    reference, reference_rate = sf.read(args.reference, dtype="float64", start=start_s * rate, stop=end_s * rate)
    if reference_rate != rate or reference.ndim != 1 or len(reference) != (end_s - start_s) * rate:
        raise ValueError("Existing independent full original reference does not match requested passage")
    summed = np.sum(solos, axis=0)
    error = reference - summed
    sum_check = {"reference_file": str(args.reference.resolve()),
                 "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                 "waveform_correlation": float(np.corrcoef(reference, summed)[0, 1]),
                 "maximum_error_pcm16_lsb": float(np.max(np.abs(error)) * 32768),
                 "rms_error_pcm16_lsb": float(np.sqrt(np.mean(error ** 2)) * 32768)}
    # Independently generated integer-PCM decodes can differ by a few dither
    # LSBs. Larger differences would invalidate this solo-isolation check.
    if sum_check["maximum_error_pcm16_lsb"] > 8:
        raise ValueError(f"Four independent solos do not reconstruct original reference: {sum_check}")
    version = subprocess.run(["openmpt123", "--short-version"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    receipt = {"decoder": "libopenmpt", "decoder_version": version, "library": location,
               "source_file": str(args.source.resolve()), "source_sha256": hashlib.sha256(raw).hexdigest(),
               "passage_start_s": start_s, "passage_end_s": end_s, "sample_rate": rate,
               "method": "Four fresh libopenmpt extended-module instances. The interactive API mutes three original MOD channels; one remains unmuted. Render from 0 s through 50 s, then crop 30–50 s.",
               "render_settings": "Same defaults as the existing independent original reference: pitch factor 1, tempo factor 1, master gain 0 dB, mono at 22050 Hz, default interpolation/Amiga filtering and volume ramping. No render parameters changed.",
               "level_processing": "None. Native signed 16-bit mono output saved directly; no gain, normalization, limiting or remixing.",
               "tracks": receipts, "sum_of_solos_check": sum_check,
               "scope": "Independent original-MOD track isolation. It does not use the experiment's timeline renderer or approximate SID instruments.",
               "api_reference": "https://lib.openmpt.org/doc/libopenmpt__ext_8h.html"}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"tracks": receipts, "sum_of_solos_check": sum_check}, indent=2))


if __name__ == "__main__":
    main()
