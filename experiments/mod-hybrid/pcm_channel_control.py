"""Build and record an original-sample C64 control for MOD track 2 only.

The original track's first 50 seconds play inside the C64. All SID oscillators
are muted. A private player copy uses the entire four-bit D418 DAC range around
baseline 8, rather than reserving loudness for accompanying SID instruments.
The 30–50 s passage is cropped only after actual VICE recording.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from build_c64 import PCM_RATE, asm_bytes, decode_packed, make_data, normalized, pack_groups
from mod_reader import load_mod
from run_vice import capture
from sequence_loss import SequenceLoss
from timeline import build_timeline


HERE = Path(__file__).resolve().parent
PAULA_CLOCK = 3546894.6


def prepare(source: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bank_out = out / "source-bank"
    bank_out.mkdir(exist_ok=True)
    mod = load_mod(source)
    timeline = build_timeline(mod)
    ticks = [tick for tick in timeline["ticks"] if tick["time_s"] < 50 - 1e-8]
    if len(ticks) != 2500:
        raise ValueError("Expected 50 seconds of original score")
    sample_ids = sorted({tick["channels"][1]["playing_sample"] for tick in ticks
                         if tick["channels"][1]["playing_sample"]})
    divisor = 8
    bank = []
    for instrument in sample_ids:
        sample = mod["samples"][instrument - 1]
        original = np.frombuffer(sample["data"], dtype=np.int8).astype(np.float64) / 128
        # Shared gain 1 preserves relative sample amplitudes. A divisor of 8
        # keeps every actual playback increment below one bank sample per IRQ.
        resampled = resample_poly(original, 1, divisor)
        quantized = np.clip(np.rint(resampled * 7.5 + 8), 0, 15).astype(np.uint8)
        start = round(sample["loop_start"] / divisor)
        length = round(sample["loop_length"] / divisor) if sample["loop_length"] > 2 else 0
        if length:
            length = min(length, len(quantized) - start)
        path = bank_out / f"sample-{instrument:02d}.bin"
        path.write_bytes(quantized.tobytes())
        bank.append({"id": instrument, "data_file": str(path.resolve()), "bytes": len(quantized),
                     "loop_start": start, "loop_length": length, "base_divisor": divisor,
                     "sample_gain_before_quantization": 1.0})
    arranged = []
    for tick in ticks:
        channel = tick["channels"][1]
        playback_rate = PAULA_CLOCK / channel["period"] if channel["period"] else 0
        step = round(playback_rate / divisor / PCM_RATE * 256)
        if not 0 <= step <= 256:
            raise ValueError("PCM control's fixed bank divisor would permit undersampled playback")
        arranged.append({key: tick[key] for key in ("time_s", "duration_s", "order", "pattern", "row", "tick")} | {
            "sid": [{"frequency": 0, "volume": 0, "wave": 0x10, "pulse": 2048, "trigger": False}
                    for _ in range(3)],
            "pcm": [{"sample": channel["playing_sample"], "step": step,
                     "volume": channel["volume"], "trigger": channel["trigger"]}],
        })
    arrangement = {"title": "Stardust Memories: original MOD track 2 PCM control", "duration_s": 50.0,
                   "pcm_rate_hz": PCM_RATE, "pal_clock_hz": 985248,
                   "pcm_bank": bank, "ticks": arranged,
                   "mapping": "Original MOD track2 to the single PCM cursor; all three SID oscillators muted"}
    arrangement_path = out / "arrangement.json"
    arrangement_path.write_text(json.dumps(arrangement, separators=(",", ":")) + "\n")
    candidates = [pack_groups(arranged, mode) for mode in ("row", "order", "16", "32", "48", "64")]
    packed = min(candidates, key=lambda candidate: candidate["bytes"])
    if decode_packed(packed) != [normalized(tick) for tick in arranged]:
        raise ValueError("PCM score packing changed original channel state")
    build_out = out / "c64"
    build_out.mkdir(exist_ok=True)
    generated, bank_receipt = make_data(arrangement, packed, build_out)
    table = bytes(min(15, max(0, 8 + round((sample - 8) * level / 15)))
                  for level in range(16) for sample in range(16))
    # Only the private generated data is changed. The shared packer, runtime
    # and other arrangements stay untouched.
    before, after = generated.split("pcm_volume_table:\n", 1)
    _, descriptors = after.split("bank_start_lo:\n", 1)
    generated = before + "pcm_volume_table:\n" + asm_bytes(table) + "\nbank_start_lo:\n" + descriptors
    (build_out / "data.asm").write_text(generated)
    original_player = (HERE / "c64_player.asm").read_text()
    if original_player.count("lda #12") != 2:
        raise ValueError("Shared player changed; review the private idle-baseline adjustment")
    private_player = original_player.replace("lda #12", "lda #8")
    player_path = build_out / "pcm-player.asm"
    player_path.write_text(private_player)
    driver = build_out / "stardust.asm"
    driver.write_text(f'.const SID_COUNT = 3\n.const PCM_COUNT = 1\n#import "{player_path.resolve()}"\n'
                      f'#import "{(build_out / "data.asm").resolve()}"\n')
    program = build_out / "stardust.prg"
    command = [str(Path.home() / ".local/bin/kickass"), str(driver.resolve()),
               "-o", str(program.resolve()), "-symbolfile"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (build_out / "build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"PCM control assembly failed: {build_out / 'build.log'}")
    symbols = {name: int(address, 16) for name, address in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (build_out / "stardust.sym").read_text())}
    if symbols["program_end"] > 0xD000:
        raise ValueError("PCM control exceeds declared resident RAM")
    receipt = {"title": arrangement["title"], "source_sha256": mod["sha256"],
               "input": str(arrangement_path.resolve()), "arrangement_sha256": hashlib.sha256(arrangement_path.read_bytes()).hexdigest(),
               "prg_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
               "prg_bytes": program.stat().st_size, "program_end": symbols["program_end"],
               "duration_s": 50.0, "ticks": len(arranged), "sid_voices": 3, "pcm_voices": 1,
               "pcm_rate_hz": PCM_RATE, "pcm_bank": bank_receipt, "labels": symbols,
               "stream_bytes": packed["bytes"], "roundtrip_verified": True,
               "trigger_count": sum(tick["pcm"][0]["trigger"] for tick in arranged),
               "bank_divisor": divisor, "maximum_8_8_step": max(tick["pcm"][0]["step"] for tick in arranged),
               "dac_lookup": "clamp(8 + round((sample_nibble - 8) * volume_level / 15), 0, 15)",
               "dac_volume_level": "Original MOD volume0..64 quantized to0..15 by shared backend",
               "private_runtime_changes": "Startup and inactive single-PCM D418 baseline changed12to8 in a private player copy; no IRQ or sequencer changes",
               "sample_processing": "Original signed8-bit samples, common gain1, polyphase lowpass downsample by8, four-bit quantization. Original per-note playback rate divided by8; loops scaled to bank coordinates.",
               "limitations": "Four-bit PCM and3848.625Hz DAC clock (Nyquist1924.3125Hz), quantized sample cursors, loop points and volume. Analog6581DAC nonlinearities remain. This controls waveform preservation versus SID approximation; it is not an Amiga-quality reproduction.",
               "source_digests": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                  for name in ("pcm_channel_control.py", "build_c64.py", "c64_player.asm", "timeline.py")},
               "private_player_sha256": hashlib.sha256(player_path.read_bytes()).hexdigest()}
    (build_out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (out / "prepare.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "sources/stardust-memories.mod")
    parser.add_argument("--out", type=Path, default=HERE / "results/channel-fit-2/pcm-control")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    receipt = prepare(args.source, args.out)
    print(json.dumps({key: receipt[key] for key in ("duration_s", "prg_bytes", "program_end", "stream_bytes", "trigger_count")}), flush=True)
    if args.prepare_only:
        return
    captured = capture(args.out / "c64/stardust.prg", args.out / "c64/stardust.sym",
                       args.out / "vice", 50.0, "both")
    audio, rate = sf.read(args.out / "vice/stardust-vice.wav", start=30 * 22050, stop=50 * 22050)
    if rate != 22050 or len(audio) != 20 * rate:
        raise ValueError("PCM control capture is not a complete20-second phrase")
    phrase = args.out / "phrase-vice.wav"
    sf.write(phrase, audio, rate, subtype="PCM_16")
    target, target_rate = sf.read(HERE / "results/channel-solos/original/track-2.wav")
    if target_rate != rate:
        raise ValueError("Original solo rate differs from control capture")
    objective = SequenceLoss(target, rate).measure(audio)
    final = {"prepare": receipt, "capture": captured,
             "phrase": str(phrase.resolve()), "phrase_sha256": hashlib.sha256(phrase.read_bytes()).hexdigest(),
             "passage_start_s": 30, "passage_duration_s": 20,
             "sequence_objective": objective,
             "audio_processing": "Actual VICE capture, clock-anchored crop and DC removal from shared capture tool. This phrase receives no listening gain and no host-side mixing."}
    (args.out / "receipt.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps({"phrase": str(phrase.resolve()), "sequence_objective": objective}, indent=2), flush=True)


if __name__ == "__main__":
    main()
