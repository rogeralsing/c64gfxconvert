"""Pack the complete arranged MOD timeline and build a real PAL C64 PRG.

The runtime supports two SID tones with two PCM cursors, or three SID tones
with one PCM cursor. It targets the original 6581 volume DAC; changing $D418
also modulates the SID tones.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
PCM_RATE = 985248 / 256


def volume(value: int) -> int:
    if not 0 <= value <= 64:
        raise ValueError("Volume outside 0..64")
    return min(15, (value * 15 + 32) // 64)


def normalized(tick: dict) -> tuple:
    sid = tuple((int(v["frequency"]), volume(v["volume"]), int(v["wave"]), int(v["pulse"]), bool(v["trigger"])) for v in tick["sid"])
    pcm = tuple((int(v["sample"]), int(v["step"]), volume(v["volume"]), bool(v["trigger"])) for v in tick["pcm"])
    if (len(sid), len(pcm)) not in ((2, 2), (3, 1)):
        raise ValueError("Backend supports two SID/two PCM or three SID/one PCM logical voices")
    if any(not 0 <= v[0] <= 65535 or v[2] not in (0x10, 0x20, 0x40, 0x80) or not 0 <= v[3] <= 4095 for v in sid):
        raise ValueError("SID state outside supported register values")
    if any(not 0 <= v[0] <= 31 or not 0 <= v[1] <= 65535 for v in pcm):
        raise ValueError("PCM ID/step outside backend bounds")
    return sid, pcm


def packet(current: tuple, previous: tuple | None) -> bytes | None:
    mask = 0
    parts = []
    for index, values in enumerate(current[0]):
        old = previous[0][index] if previous else None
        flags = sum(bit for bit, field in ((1, 0), (2, 1), (4, 2), (8, 3)) if old is None or values[field] != old[field])
        flags |= 16 if values[4] else 0
        if not flags:
            continue
        mask |= 1 << index
        data = bytearray([flags])
        for bit, field, width in ((1, 0, 2), (2, 1, 1), (4, 2, 1), (8, 3, 2)):
            if flags & bit:
                data.extend(values[field].to_bytes(width, "little"))
        parts.append(data)
    for index, values in enumerate(current[1]):
        old = previous[1][index] if previous else None
        flags = sum(bit for bit, field in ((1, 0), (2, 1), (4, 2)) if old is None or values[field] != old[field])
        flags |= 8 if values[3] else 0
        if not flags:
            continue
        mask |= 1 << (len(current[0]) + index)
        data = bytearray([flags])
        for bit, field, width in ((1, 0, 1), (2, 1, 2), (4, 2, 1)):
            if flags & bit:
                data.extend(values[field].to_bytes(width, "little"))
        parts.append(data)
    return bytes([0x80 | mask]) + b"".join(parts) if mask else None


def encode_group(ticks: list[dict]) -> bytes:
    stream = bytearray()
    previous = None
    held = 0

    def flush() -> None:
        nonlocal held
        while held:
            count = min(127, held)
            stream.append(count)
            held -= count

    for tick in ticks:
        current = normalized(tick)
        change = packet(current, previous)
        if change is None:
            held += 1
        else:
            flush()
            stream.extend(change)
        previous = current
    flush()
    stream.append(0)
    return bytes(stream)


def pack_groups(ticks: list[dict], mode: str) -> dict:
    groups = []
    for index, tick in enumerate(ticks):
        key = (tick["order"], tick["row"]) if mode == "row" else tick["order"] if mode == "order" else index // int(mode)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(tick)
    unique, lookup, playlist = [], {}, []
    for _, group in groups:
        encoded = encode_group(group)
        if encoded not in lookup:
            lookup[encoded] = len(unique)
            unique.append(encoded)
        playlist.append(lookup[encoded])
    return {"mode": mode, "blocks": unique, "playlist": playlist,
            "sid_count": len(ticks[0]["sid"]), "pcm_count": len(ticks[0]["pcm"]),
            "bytes": sum(map(len, unique)) + 2 * (len(playlist) + 1)}


def decode_packed(packed: dict) -> list[tuple]:
    """Check the emitted packet format against the independently held timeline."""
    states = [[(0, 0, 0x40, 2048, False)] * packed["sid_count"], [(0, 0, 0, False)] * packed["pcm_count"]]
    ticks = []
    for block_id in packed["playlist"]:
        block = packed["blocks"][block_id]
        position = 0

        def get(width: int = 1) -> int:
            nonlocal position
            value = int.from_bytes(block[position:position + width], "little")
            position += width
            return value

        while True:
            command = get()
            if command == 0:
                break
            states = [[tuple(v[:-1]) + (False,) for v in voices] for voices in states]
            if command < 128:
                ticks.extend((tuple(states[0]), tuple(states[1])) for _ in range(command))
                continue
            for group, count, fields in ((0, packed["sid_count"], ((1, 0, 2), (2, 1, 1), (4, 2, 1), (8, 3, 2))),
                                         (1, packed["pcm_count"], ((1, 0, 1), (2, 1, 2), (4, 2, 1)))):
                for index in range(count):
                    if command & (1 << (index + packed["sid_count"] * group)):
                        flags = get()
                        values = list(states[group][index])
                        for bit, field, width in fields:
                            if flags & bit:
                                values[field] = get(width)
                        values[-1] = bool(flags & (16 if group == 0 else 8))
                        states[group][index] = tuple(values)
            ticks.append((tuple(states[0]), tuple(states[1])))
    return ticks


def asm_bytes(data: bytes) -> str:
    return "\n".join("    .byte " + ",".join(f"${v:02x}" for v in data[offset:offset + 24]) for offset in range(0, len(data), 24))


def make_data(arrangement: dict, packed: dict, out: Path) -> tuple[str, dict]:
    lines = [".align $100", "pcm_volume_table:"]
    if packed["pcm_count"] == 1:
        table = bytes(min(15, max(0, 12 + round((sample - 8) * level / 40))) for level in range(16) for sample in range(16))
    else:
        table = bytes(min(7, max(0, 4 + round((sample - 8) * level / 30))) for level in range(16) for sample in range(16))
    lines.append(asm_bytes(table))
    entries = {sample["id"]: dict(sample) for sample in arrangement["pcm_bank"]}
    bank_data = {}
    bank_receipt = []
    for index, sample in entries.items():
        data = Path(sample["data_file"]).read_bytes()
        if not data or max(data) > 15:
            raise ValueError(f"PCM bank {index} must contain unsigned four-bit values in bytes")
        start, length = int(sample["loop_start"]), int(sample["loop_length"])
        source_length = len(data)
        if length:
            if start < 0 or start + length > len(data):
                raise ValueError("PCM loop exceeds sample")
            data = data[:start + length]
            max_step = max(v["step"] for tick in arrangement["ticks"] for v in tick["pcm"] if v["sample"] == index)
            copies = max(1, math.ceil((max_step / 256 + 1) / length))
            data = data[:start] + data[start:] * copies
            length *= copies
        bank_data[index] = data
        sample["effective_loop_start"] = start
        sample["effective_loop_length"] = length
        bank_receipt.append({"id": index, "source_bytes": source_length, "stored_bytes": len(data),
                             "loop_start": start, "loop_length": length,
                             "source_sha256": hashlib.sha256(Path(sample["data_file"]).read_bytes()).hexdigest()})
    for name, expression in (
        ("bank_start_lo", lambda i: f"<pcm_sample_{i}"),
        ("bank_start_hi", lambda i: f">pcm_sample_{i}"),
        ("bank_end_lo", lambda i: f"<(pcm_sample_{i}+{len(bank_data[i])})"),
        ("bank_end_hi", lambda i: f">(pcm_sample_{i}+{len(bank_data[i])})"),
        ("bank_loop_lo", lambda i: f"<(pcm_sample_{i}+{entries[i]['effective_loop_start']})"),
        ("bank_loop_hi", lambda i: f">(pcm_sample_{i}+{entries[i]['effective_loop_start']})"),
        ("bank_loop_enabled", lambda i: "1" if entries[i]["effective_loop_length"] else "0"),
    ):
        lines.append(name + ":")
        lines.append("    .byte " + ",".join(expression(i) if i in entries else "0" for i in range(max(entries) + 1)))
    lines.append("song_playlist:")
    for offset in range(0, len(packed["playlist"]), 12):
        lines.append("    .word " + ",".join(f"song_block_{i}" for i in packed["playlist"][offset:offset + 12]))
    lines.append("    .word 0")
    for index, block in enumerate(packed["blocks"]):
        lines += [f"song_block_{index}:", asm_bytes(block)]
    lines.append("pcm_bank_begin:")
    for index, data in sorted(bank_data.items()):
        filename = out / f"sample-{index:02d}.bin"
        filename.write_bytes(data)
        lines += [f"pcm_sample_{index}:", f'    .import binary "{filename.resolve()}"']
    lines += ["pcm_bank_end:", "program_end:", '.assert "Program must remain below I/O", program_end <= $d000, true']
    return "\n".join(lines) + "\n", {"samples": bank_receipt, "bank_bytes": sum(map(len, bank_data.values())),
                                             "volume_table_bytes": len(table), "descriptor_bytes": 7 * (max(entries) + 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "results/arrangement.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/c64")
    parser.add_argument("--assembler", type=Path, default=Path.home() / ".local/bin/kickass")
    args = parser.parse_args()
    arrangement = json.loads(args.input.read_text())
    ticks = arrangement["ticks"]
    if abs(arrangement["pcm_rate_hz"] - PCM_RATE) > 1e-6 or any(abs(t["duration_s"] - .02) > 1e-8 for t in ticks):
        raise ValueError("Backend requires 3848.625 Hz PCM and ideal 50 Hz arrangement ticks")
    candidates = [pack_groups(ticks, mode) for mode in ("row", "order", "16", "32", "48", "64")]
    packed = min(candidates, key=lambda item: item["bytes"])
    if decode_packed(packed) != [normalized(tick) for tick in ticks]:
        raise ValueError("Packed bytecode does not reproduce the entire quantized arrangement")
    args.out.mkdir(parents=True, exist_ok=True)
    generated, bank_receipt = make_data(arrangement, packed, args.out)
    (args.out / "data.asm").write_text(generated)
    main_asm = args.out / "stardust.asm"
    main_asm.write_text(f'.const SID_COUNT = {packed["sid_count"]}\n.const PCM_COUNT = {packed["pcm_count"]}\n'
                        f'#import "{(HERE / "c64_player.asm").resolve()}"\n#import "{(args.out / "data.asm").resolve()}"\n')
    prg = args.out / "stardust.prg"
    command = [str(args.assembler), str(main_asm.resolve()), "-o", str(prg.resolve()), "-symbolfile"]
    build = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (args.out / "build.log").write_text(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError(f"Assembler failed; inspect {args.out / 'build.log'}")
    symbol_text = (args.out / "stardust.sym").read_text()
    labels = {key: int(value, 16) for key, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", symbol_text)}
    for name in ("start", "done", "song_started", "program_end", "played_tick_count", "underrun_counter"):
        if name not in labels:
            raise ValueError(f"Required exported symbol missing: {name}")
    receipt = {"input": str(args.input.resolve()), "arrangement_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
               "title": arrangement["title"], "duration_s": arrangement["duration_s"], "ticks": len(ticks),
               "pcm_rate_hz": PCM_RATE, "sample_timer_cycles": 256,
               "sid_voices": packed["sid_count"], "pcm_voices": packed["pcm_count"],
               "pcm_dac_baseline": 12 if packed["pcm_count"] == 1 else 8,
               "compression": {"chosen_grouping": packed["mode"], "unique_blocks": len(packed["blocks"]),
                               "playlist_entries": len(packed["playlist"]), "stream_bytes": packed["bytes"],
                               "alternatives": {item["mode"]: item["bytes"] for item in candidates},
                               "all_ticks_roundtrip_verified": True},
               "pcm_bank": bank_receipt, "prg_bytes": prg.stat().st_size,
               "load_address": int.from_bytes(prg.read_bytes()[:2], "little"), "program_end": labels["program_end"],
               "labels": labels, "prg_sha256": hashlib.sha256(prg.read_bytes()).hexdigest(),
               "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in ("build_c64.py", "c64_player.asm")},
               "scope": f"PAL C64, first target 6581; {packed['sid_count']} SID tones plus {packed['pcm_count']} PCM software voices through D418. Digi also modulates SID master volume. No REU or external streaming; all song data resident below D000."}
    if receipt["program_end"] > 0xD000 or receipt["prg_bytes"] >= 65536:
        raise ValueError("Resident program exceeds declared C64 RAM budget")
    (args.out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in ("ticks", "duration_s", "prg_bytes", "program_end", "compression")}), flush=True)


if __name__ == "__main__":
    main()
