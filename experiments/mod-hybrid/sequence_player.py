"""Build and verify a C64 player for a fitted single-voice SID frame sequence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
CLOCK = 985248
ALLOWED = tuple(range(7)) + tuple(range(21, 25))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_frames(source: dict) -> list[list[tuple[int, int]]]:
    if source.get("model") != "6581":
        raise ValueError("This export targets MOS6581")
    if not 1000 <= source["frame_cycles"] <= 65536:
        raise ValueError("Frame period outside the CIA timer range")
    state = dict.fromkeys(ALLOWED, 0)
    state[24] = 15
    result = []
    for index, frame in enumerate(source["frames"]):
        changed = []
        for register, value in frame:
            if not isinstance(register, int) or not 0 <= register <= 24 or not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError(f"Invalid register write in frame{index}")
            if register not in ALLOWED and (index != 0 or value != 0):
                raise ValueError("Only initial zeroing may write the other SID voices")
            if register == 24 and value & 15 != 15 and index != 0:
                raise ValueError("This player requires constant master volume15")
            if state.get(register, 0) != value:
                changed.append((register, value))
                state[register] = value
        if len(changed) > 127 or 100 + 32 * len(changed) >= source["frame_cycles"]:
            raise ValueError(f"Frame{index} exceeds the conservative decode cycle budget")
        result.append(changed)
    if not result or len(result) > 65535:
        raise ValueError("Frame count must fit the exported16bit runtime counter")
    return result


def encode(frames: list) -> bytes:
    result = bytearray()
    held = 0

    def flush():
        nonlocal held
        while held:
            count = min(127, held)
            result.append(128 | count)
            held -= count

    for frame in frames:
        if not frame:
            held += 1
        else:
            flush()
            result.append(len(frame))
            for register, value in frame:
                result.extend((register, value))
    flush()
    result.append(0)
    return bytes(result)


def pack(frames: list, size: int) -> dict:
    blocks, lookup, playlist = [], {}, []
    for start in range(0, len(frames), size):
        data = encode(frames[start:start + size])
        if data not in lookup:
            lookup[data] = len(blocks)
            blocks.append(data)
        playlist.append(lookup[data])
    return {"group_frames": size, "blocks": blocks, "playlist": playlist,
            "bytes": sum(map(len, blocks)) + 2 * (len(playlist) + 1)}


def decode(packed: dict) -> list:
    result = []
    for block_id in packed["playlist"]:
        block = packed["blocks"][block_id]
        position = 0
        while block[position]:
            command = block[position]
            position += 1
            if command & 128:
                result.extend([] for _ in range(command & 127))
            else:
                result.append([tuple(block[i:i + 2]) for i in range(position, position + 2 * command, 2)])
                position += 2 * command
        if position + 1 != len(block):
            raise ValueError("Invalid packed block boundary")
    return result


def build_frames(jsonpath: Path | str, out: Path | str) -> dict:
    jsonpath, out = Path(jsonpath), Path(out)
    source = json.loads(jsonpath.read_text())
    frames = canonical_frames(source)
    choices = [pack(frames, size) for size in (16, 32, 48, 64, 128, 256, len(frames))]
    packed = min(choices, key=lambda item: item["bytes"])
    if decode(packed) != frames:
        raise ValueError("Packed frames do not reproduce the canonical ordered register events")
    out.mkdir(parents=True, exist_ok=True)
    data = ["song_playlist:"]
    for offset in range(0, len(packed["playlist"]), 12):
        data.append("    .word " + ",".join(f"frame_block_{i}" for i in packed["playlist"][offset:offset + 12]))
    data.append("    .word 0")
    for index, block in enumerate(packed["blocks"]):
        data.append(f"frame_block_{index}:")
        for offset in range(0, len(block), 24):
            data.append("    .byte " + ",".join(f"${value:02x}" for value in block[offset:offset + 24]))
    data.extend(("program_end:", '.assert "Program below I/O", program_end <= $d000, true'))
    (out / "frames-data.asm").write_text("\n".join(data) + "\n")
    assembly = out / "sequence.asm"
    assembly.write_text(f'.const FRAME_CYCLES = {source["frame_cycles"]}\n'
                        f'#import "{(HERE / "sequence_player.asm").resolve()}"\n'
                        f'#import "{(out / "frames-data.asm").resolve()}"\n')
    prg = out / "sequence.prg"
    command = [str(Path.home() / ".local/bin/kickass"), str(assembly.resolve()), "-o", str(prg.resolve()), "-symbolfile"]
    compiled = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / "build.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise RuntimeError(f"Assembler failed; inspect {out / 'build.log'}")
    symbol_path = out / "sequence.sym"
    labels = {name: int(value, 16) for name, value in
              re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbol_path.read_text())}
    if labels["program_end"] > 0xd000:
        raise ValueError(f"Packed payload{packed['bytes']}bytes exceeds resident RAM")
    receipt = {"input": str(jsonpath.resolve()), "input_sha256": sha(jsonpath),
               "program": str(prg.resolve()), "symbols": str(symbol_path.resolve()), "program_sha256": sha(prg),
               "program_bytes": prg.stat().st_size, "program_end": labels["program_end"], "labels": labels,
               "frames": len(frames), "frame_cycles": source["frame_cycles"],
               "actual_rate_hz": CLOCK / source["frame_cycles"], "duration_s": source["duration_s"],
               "clock_duration_s": len(frames) * source["frame_cycles"] / CLOCK,
               "sample_rate": source["sample_rate"], "maximum_writes_per_frame": max(map(len, frames)),
               "packed_bytes": packed["bytes"], "group_frames": packed["group_frames"],
               "unique_blocks": len(packed["blocks"]), "playlist_entries": len(packed["playlist"]),
               "ordered_events_roundtrip_verified": True,
               "source_sha256": {name: sha(HERE / name) for name in ("sequence_player.py", "sequence_player.asm")}}
    (out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def read_trace(path: Path) -> tuple[list, int]:
    events, cycle = [], 0
    for line in path.open():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        cycle += delta
        events.append((cycle, register & 31, value))
    clear = [(r, 0) for r in range(24, -1, -1)]
    for index in range(len(events) - 25):
        if [(r, v) for _, r, v in events[index:index + 25]] == clear:
            cycle, register, value = events[index + 25]
            if (register, value) == (24, 15):
                return events, cycle
    raise ValueError("Cannot locate the explicit frame0 volume bus anchor")


def verify_trace(source: dict, trace: Path) -> dict:
    import numpy as np
    events, anchor = read_trace(trace)
    history = {register: ([], []) for register in ALLOWED}
    for cycle, register, value in events:
        if register in history:
            history[register][0].append(cycle)
            history[register][1].append(value)
    state = dict.fromkeys(ALLOWED, 0)
    state[24] = 15
    expected = []
    for frame in source["frames"]:
        state.update(frame)
        expected.append([state[r] for r in ALLOWED])
    expected = np.asarray(expected)
    checks = []
    for observation_ms in (1, 2):
        times = anchor + np.arange(len(expected)) * source["frame_cycles"] + round(observation_ms * CLOCK / 1000)
        actual = np.zeros_like(expected)
        for column, register in enumerate(ALLOWED):
            cycles, values = history[register]
            indexes = np.searchsorted(cycles, times, side="right") - 1
            if np.any(indexes < 0):
                raise ValueError("Missing initial register value in bus trace")
            actual[:, column] = np.asarray(values)[indexes]
        bad = np.argwhere(actual != expected)
        checks.append({"observation_ms": observation_ms, "mismatched_register_values": len(bad),
                       "examples": [{"frame": int(i), "register": ALLOWED[int(j)],
                                     "expected": int(expected[i, j]), "actual": int(actual[i, j])} for i, j in bad[:12]]})
    receipt = {"anchor_cycle": anchor, "frames_checked": len(expected), "registers": list(ALLOWED),
               "checks": checks, "passed": all(c["mismatched_register_values"] == 0 for c in checks)}
    if not receipt["passed"]:
        raise ValueError(f"Actual C64 register frames differ from fitted source: {receipt}")
    return receipt


def capture_frames(jsonpath: Path | str, out: Path | str, mode: str = "both") -> dict:
    import numpy as np
    import soundfile as sf
    jsonpath, out = Path(jsonpath), Path(out)
    build = json.loads((out / "build.json").read_text())
    if sha(jsonpath) != build["input_sha256"] or sha(Path(build["program"])) != build["program_sha256"]:
        raise ValueError("Capture input or executable changed since build")
    source = json.loads(jsonpath.read_text())
    labels = build["labels"]
    capture_dir = out / "vice"
    capture_dir.mkdir(exist_ok=True)
    stats = capture_dir / "runtime.bin"
    monitor = capture_dir / "capture.mon"
    monitor.write_text(f'load "{build["program"]}" 0\n'
                       f'break exec ${labels["done"]:04x}\ng ${labels["start"]:04x}\n'
                       f'step 20000\nbsave "{stats.resolve()}" 0 $0026 $0029\nquit\n')
    trace, wav = capture_dir / "registers.txt", capture_dir / "vice-raw.wav"
    duration = max(source["duration_s"], build["clock_duration_s"])
    rate = source["sample_rate"]
    command = ["/opt/homebrew/bin/x64sc", "-default", "-console", "-pal", "-seed", "1",
               "-sidengine", "1", "-sidmodel", "0", "-residsamp", "2", "-soundrate", str(rate),
               "-soundoutput", "1", "-soundvolume", "100", "-initbreak", "ready",
               "-moncommands", str(monitor.resolve()), "-limitcycles", str(round((duration + 15) * CLOCK))]
    receipt_path = capture_dir / "capture.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if receipt.get("program_sha256", build["program_sha256"]) != build["program_sha256"]:
        receipt = {}
    receipt.update(program_sha256=build["program_sha256"], input_sha256=build["input_sha256"],
                   model="PAL MOS6581", engine="VICE reSID (SidEngine=1)",
                   source_renderer_engine=source.get("renderer_engine", "unspecified"))
    for capture_mode in (("registers", "audio") if mode == "both" else (mode,)):
        options = (["-sounddev", "dump", "-soundarg", str(trace.resolve()), "-warp"] if capture_mode == "registers" else
                   ["-sounddev", "wav", "-soundarg", str(wav.resolve()), "+warp", "-speed", "100"])
        print(f"Sequence VICE {capture_mode} capture started", flush=True)
        stats.unlink(missing_ok=True)
        completed = subprocess.run(command + options, capture_output=True, text=True, timeout=duration + 60)
        (capture_dir / f"{capture_mode}.log").write_text(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"VICE failed; inspect {capture_dir / (capture_mode + '.log')}")
        raw = stats.read_bytes()
        if len(raw) != 4:
            raise ValueError("Incomplete C64 runtime counters")
        counters = {"played_frames": int.from_bytes(raw[:2], "little"), "underruns": int.from_bytes(raw[2:], "little")}
        if counters["played_frames"] != len(source["frames"]) or counters["underruns"]:
            raise ValueError(f"C64 runtime did not finish cleanly:{counters}")
        receipt.setdefault("runtime", {})[capture_mode] = counters
        if capture_mode == "registers":
            receipt["trace"] = verify_trace(source, trace)
        else:
            if "trace" not in receipt:
                receipt["trace"] = verify_trace(source, trace)
            pcm, actual_rate = sf.read(wav, always_2d=True)
            if actual_rate != rate or pcm.shape[1] != 1:
                raise ValueError("Unexpected captured PCM format")
            anchor = round(receipt["trace"]["anchor_cycle"] * rate / CLOCK)
            count = round(source["duration_s"] * rate)
            audio = pcm[anchor:anchor + count, 0].copy()
            if len(audio) != count:
                raise ValueError("Incomplete captured phrase")
            audio -= audio.mean()
            peak = float(np.max(np.abs(audio)))
            if peak < 1e-5:
                raise ValueError("Captured fitted phrase is silent")
            sf.write(capture_dir / "phrase-vice.wav", audio, rate, subtype="PCM_16")
            gain = min(8, .92 / peak) if peak else 1
            sf.write(capture_dir / "phrase-listening.wav", audio * gain, rate, subtype="PCM_16")
            receipt["audio"] = {"frames": count, "sample_rate": rate, "crop_start_frame": anchor,
                                "duration_s": count / rate, "raw_peak": peak,
                                "raw_rms": float(np.sqrt(np.mean(audio ** 2))), "listening_gain": gain,
                                "note": "Actual VICE output; constant listening gain and DC removal only."}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--mode", choices=("both", "registers", "audio"), default="both")
    args = parser.parse_args()
    result = build_frames(args.input, args.out)
    print(json.dumps({key: result[key] for key in ("program", "program_bytes", "frames", "packed_bytes")}))
    if args.capture:
        print(json.dumps(capture_frames(args.input, args.out, args.mode), indent=2))


if __name__ == "__main__":
    main()
