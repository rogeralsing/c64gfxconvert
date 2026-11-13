#!/usr/bin/env python3
"""Build an independent sampled-WAV trial with the native SID3 latch."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import zlib

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

HERE = Path(__file__).resolve().parent
CLOCK, PERIOD = 985248, 126
DEFAULT_SOURCE = HERE / "assets/whistle-gif-6s.wav"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(source: Path, output: Path) -> dict:
    original, rate = sf.read(source, dtype="float64", always_2d=True)
    if original.shape[1] != 1:
        raise ValueError("Supply a mono source; this trial does not silently mix channels.")
    mono = original[:, 0]
    source_dc = float(mono.mean())
    mono = mono - source_dc
    ratio = Fraction(CLOCK, PERIOD * rate)
    count = round(len(mono) * CLOCK / (rate * PERIOD))
    sampled = resample_poly(mono, ratio.numerator, ratio.denominator)[:count]
    if count < 257 or count % 256 == 0 or count // 256 > 253:
        raise ValueError("This bounded trial needs a partial last page and at most 254 pages.")
    peak = float(np.max(np.abs(sampled)))
    if peak == 0:
        raise ValueError("The supplied source is silent.")
    # One fixed source gain leaves symmetric headroom. Codes retain neutral128;
    # their four-bit indices never write the SID master-volume register.
    gain = 112 / peak
    target = np.clip(np.rint(sampled * gain + 128), 0, 255).astype(np.uint8)
    codebook = (np.arange(16, dtype=np.uint8) * 16)
    indices = np.clip(np.rint((target.astype(np.float64)) / 16), 0, 15).astype(np.uint8)
    expected = codebook[indices]
    pages = math.ceil(count / 256)
    padded_indices = np.full(pages * 256, 8, dtype=np.uint8)
    padded_indices[:count] = indices
    packed = (padded_indices[0::2] << 4) | padded_indices[1::2]
    decoded = np.empty(len(padded_indices), dtype=np.uint8)
    decoded[0::2] = codebook[packed >> 4]
    decoded[1::2] = codebook[packed & 15]
    assert np.array_equal(decoded[:count], expected)
    assert np.all(decoded[count:] == 128)
    (output / "expected-input.bin").write_bytes(expected.tobytes())
    (output / "target-input.bin").write_bytes(target.tobytes())
    (output / "packed.bin").write_bytes(packed.tobytes())
    (output / "high-lookup.bin").write_bytes(codebook[np.arange(256) >> 4].tobytes())
    (output / "low-lookup.bin").write_bytes(codebook[np.arange(256) & 15].tobytes())
    error = expected.astype(np.float64) - target
    signal = target.astype(np.float64) - 128
    result = {
        "source": str(source.resolve()), "sourceSha256": digest(source),
        "sourceRate": rate, "sourceFrames": len(mono), "sourceDurationSeconds": len(mono) / rate,
        "clock": CLOCK, "period": PERIOD, "nativeRate": CLOCK / PERIOD,
        "sampleCount": count, "nativeDurationSeconds": count * PERIOD / CLOCK,
        "pageCount": pages, "fullPages": count // 256, "finalValues": count % 256,
        "packedClipBytes": math.ceil(count / 2), "packedResidentBytes": len(packed),
        "guardSampleCount": len(decoded) - count,
        "packedZlib9Bytes": len(zlib.compress(packed.tobytes(), 9)),
        "codebook": codebook.tolist(), "usedLevels": np.unique(expected).tolist(),
        "quantization": "Nearest linear four-bit value; fixed unsigned neutral128; no dithering.",
        "sourceDCRemoved": source_dc, "sourceGain": gain, "targetPeakCodes": 112,
        "quantizationRMSCodes": float(np.sqrt(np.mean(error ** 2))),
        "quantizationSNRdB": float(10 * np.log10(np.mean(signal ** 2) / np.mean(error ** 2))),
        "inputSha256": digest(output / "expected-input.bin"),
        "packedSha256": digest(output / "packed.bin"),
        "sourceProcessing": "Mono source DC removal, rational polyphase resampling to the exact PAL sample clock, one constant gain, nearest linear four-bit quantization. No EQ, denoising, dynamics or time fitting.",
        "hostPackedRoundtripPassed": True,
        "runtimePrefixes": {"inputWrites": "expected-input.bin followed by two neutral128 values", "latches": "one neutral128 prime, expected-input.bin, one neutral128 guard"},
    }
    save(output / "preparation.json", result)
    return result


def build(source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    prepared = prepare(source.resolve(), output)
    shutil.copyfile(HERE / "player.asm", output / "player.asm")
    packed = (output / "packed.bin").read_bytes()
    config = {"PACKED_START": 0x1000, "SAMPLE_COUNT": prepared["sampleCount"],
              "PAGE_COUNT": prepared["pageCount"], "FULL_PAGES": prepared["fullPages"],
              "FINAL_VALUES": prepared["finalValues"]}
    (output / "config.asm").write_text("\n".join(f".const {k} = {v}" for k, v in config.items()) + "\n")
    data = ['.pc = $0c00 "Packed high-nibble lookup"', 'high_lookup:',
            '.import binary "high-lookup.bin"', '.pc = $0d00 "Packed low-nibble lookup"',
            'low_lookup:', '.import binary "low-lookup.bin"']
    chunks, offset = [], 0
    address = config["PACKED_START"]
    while offset < len(packed):
        page = address >> 8
        if 0x70 <= page <= 0x78:
            delta = page - 0x70
            head = 5 + (delta + 1) // 2
            data += [f'.pc = ${page * 256:04x} "Distributed jitter entry"',
                     f'.fill {delta // 2},$ea']
            data += ['.byte $85,<(restore_a+1)'] if delta % 2 == 0 else ['.byte $8d,<(restore_a+1),>(restore_a+1)']
            data += ['jmp nmi_common']
            address = page * 256 + head
        size = min(256 - (address & 255), len(packed) - offset)
        data += [f'.pc = ${address:04x} "Packed source data"',
                 f'.import binary "packed.bin",{offset},{size}']
        chunks.append({"address": address, "offset": offset, "bytes": size})
        offset += size
        address += size
    data += ['packed_end:']
    (output / "data.asm").write_text("\n".join(data) + "\n")
    transitions = ['advance_source_page:', 'lda packed_read+2']
    for page in range(0x70, 0x79):
        head = 5 + (page - 0x70 + 1) // 2
        transitions += [f'cmp #{page}', 'bne !next+', f'lda #{head}',
                        'sta packed_read+1', 'rts', '!next:']
    transitions += ['rts']
    (output / "source-transitions.asm").write_text("\n".join(transitions) + "\n")
    command = ['rtk', 'proxy', str(Path.home() / '.local/bin/kickass'), str(output / 'player.asm'),
               '-o', str(output / 'player.prg'), '-symbolfile']
    completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (output / "build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    symbols = {k: int(v, 16) for k, v in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', (output / 'player.sym').read_text())}
    raw = (output / 'player.prg').read_bytes()
    load = int.from_bytes(raw[:2], 'little')
    if load + len(raw) - 2 > 0xd000:
        raise ValueError("The standalone PRG must not load through SID/VIC/CIA registers.")
    for chunk in chunks:
        actual = raw[chunk['address'] - load + 2:chunk['address'] - load + 2 + chunk['bytes']]
        assert actual == packed[chunk['offset']:chunk['offset'] + chunk['bytes']]
    result = {"program": str((output / 'player.prg').resolve()), "program_sha256": digest(output / 'player.prg'),
              "symbols": symbols, "preparation": prepared, "packedChunks": chunks,
              "bytes": len(raw), "loadAddress": load, "endExclusive": load + len(raw) - 2,
              "source_sha256": digest(HERE / 'player.asm'),
              "stateAddresses": {"boundary_count": 2, "boundary_before": 3, "generated_pages": 4, "underruns": 5, "finished": 6, "next_buffer": 7},
              "profile": {"machine": "PAL C64", "SID": "MOS8580 + digiboost", "recordingRate": 22050},
              "samplingMethod": "Linus/SounDemoN SID3 sample-and-hold; fixed master volume15; no D418 amplitudes",
              "screenOn": False, "nativePlaybackVerified": False}
    save(output / 'build.json', result)
    print(json.dumps({k: result[k] for k in ('program', 'program_sha256', 'bytes', 'endExclusive')}, indent=2))
    print(json.dumps({k: prepared[k] for k in ('sampleCount','nativeRate','nativeDurationSeconds','packedClipBytes','packedResidentBytes','packedZlib9Bytes','quantizationSNRdB')}, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=HERE / 'work/default')
    args = parser.parse_args()
    build(args.source, args.output.resolve())


if __name__ == '__main__':
    main()
