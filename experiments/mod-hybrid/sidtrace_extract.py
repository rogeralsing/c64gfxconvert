"""Extract a passage of a SID register dump into a resident replay PRG.

The VICE register dump ("delta reg val" lines) is split into the D418 digi
stream and every other SID register event. The digi is band-limited and
resampled onto the player's 256-cycle tick grid; register events become
(due_tick, register, value) packets replayed by sidtrace_player.asm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from fractions import Fraction
from scipy.signal import firwin, lfilter

HERE = Path(__file__).resolve().parent
PAL_CLOCK = 985248
TICK_CYCLES = 256
RATE = PAL_CLOCK / TICK_CYCLES


def parse_dump(path: Path) -> np.ndarray:
    rows = []
    clock = 0
    for line in path.open():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        clock += delta
        rows.append((clock, register, value))
    return np.asarray(rows, dtype=np.int64)


def extract(rows: np.ndarray, window: tuple[float, float], name: str) -> dict:
    rate = RATE
    # Anchor at the music start: the first sustained run of regular D418
    # writes. The literal first write is the kernal's register clear, which
    # precedes the tune and would bias every window.
    vol_cycles = rows[rows[:, 1] == 24][:, 0]
    gaps = np.diff(vol_cycles)
    ok = (gaps >= 60) & (gaps <= 600)
    run = np.convolve(ok.astype(int), np.ones(32, int), "valid")
    hit = np.flatnonzero(run == 32)
    if len(hit):
        anchor = int(vol_cycles[hit[0]])
    else:
        anchor = int(vol_cycles[0])
    start = anchor + round(window[0] * PAL_CLOCK)
    end = anchor + round(window[1] * PAL_CLOCK)
    n_samples = int(round((window[1] - window[0]) * rate))
    if n_samples >= 65536:
        raise ValueError("Passage too long for a 16-bit sample counter at this tick rate")

    digi = rows[(rows[:, 1] == 24) & (rows[:, 0] >= start) & (rows[:, 0] < end)]
    modes = set(np.unique(digi[:, 2] >> 4).tolist())
    if modes != {3}:
        raise ValueError(f"Unexpected D418 mode nibbles in window: {sorted(modes)}")
    # Band-limit before sampling onto the tick grid. The register stream is
    # sample-and-hold: the volume holds its last written value across the
    # player's bursts and gaps, so the staircase must be reconstructed with
    # hold semantics — linear interpolation would slide the volume across
    # every gap and smear each phrase onset.
    taps = firwin(65, 0.94 * rate / 2 / (rate / 2))
    # Filter with a margin of pre-window samples so the FIR reaches steady
    # state before the first delivered sample; without it the first ~10 ms
    # of the passage play as an audible hiccup.
    margin = 256
    grid_cycles = start + (np.arange(n_samples + margin) - margin) * TICK_CYCLES
    idx = np.searchsorted(digi[:, 0], grid_cycles, side="right") - 1
    idx = np.clip(idx, 0, len(digi) - 1)
    codes_ext = digi[idx, 2] & 15
    codes_ext = np.rint(lfilter(taps, 1.0, codes_ext.astype(float)))
    codes = np.clip(codes_ext[margin:margin + n_samples], 0, 15).astype(np.uint8)

    # Every non-D418 event from music start, ordered as captured, deduplicated
    # against each register's current state: the original rewrites every
    # register every frame, so unchanged writes are pure redundancy for a
    # replay. Events before the window collapse to tick 0 in original order,
    # reconstructing the player state at the window start.
    evs = rows[(rows[:, 1] != 24) & (rows[:, 1] <= 24) & (rows[:, 0] < end)]
    last_state = [0] * 25
    kept = []
    for cycle, register, value in evs:
        if value != last_state[register]:
            last_state[register] = value
            kept.append((cycle, register, value))
    evs = np.asarray(kept, dtype=np.int64) if kept else np.zeros((0, 3), dtype=np.int64)
    dues = np.floor((evs[:, 0] - start).astype(np.float64) / TICK_CYCLES)
    dues = np.clip(dues, 0, 65534).astype(np.uint16)
    # Preserve capture order when multiple events fall within the same tick.
    order = np.argsort(dues, kind="stable")
    dues, evs = dues[order], evs[order]
    packets = np.empty((len(evs), 4), dtype=np.uint8)
    packets[:, 0] = dues & 0xFF
    packets[:, 1] = dues >> 8
    packets[:, 2] = evs[:, 1].astype(np.uint8)
    packets[:, 3] = evs[:, 2].astype(np.uint8)
    terminator = np.array([[0xFF, 0xFF, 0x00, 0x00]], dtype=np.uint8)
    packets = np.concatenate([packets, terminator])

    if len(packets) > 65535:
        raise ValueError("Passage has more register events than the player format holds")
    return {"name": name, "codes": codes, "packets": packets, "window": window,
            "n_samples": n_samples, "digi_writes": len(digi),
            "events": len(packets) - 1, "tick_cycles": TICK_CYCLES, "rate_hz": rate}


def bytes_asm(data: bytes, per_line: int = 16) -> list[str]:
    lines = []
    for offset in range(0, len(data), per_line):
        chunk = data[offset:offset + per_line]
        lines.append("    .byte " + ",".join(f"${b:02x}" for b in chunk))
    return lines


def build(result: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    codes, packets = result["codes"], result["packets"]
    if len(codes) % 2:
        codes = np.concatenate([codes, np.zeros(1, dtype=np.uint8)])
    packed = ((codes[0::2] << 4) | codes[1::2]).astype(np.uint8)
    data_lines = ["pcm_data:"] + bytes_asm(packed.tobytes())
    data_lines += ["evt_data:"] + bytes_asm(packets.tobytes())
    data_lines.append("program_end:")
    data_lines.append('.assert "Sidtrace program below I/O", program_end <= $cf00, true')
    (out / "data.asm").write_text("\n".join(data_lines) + "\n")

    wrapper = out / "sidtrace.asm"
    d418_mode = 0x30
    tick = TICK_CYCLES
    per_frame = Fraction(PAL_CLOCK, tick * 50)
    whole = per_frame.numerator // per_frame.denominator
    frac_part = per_frame - whole
    q = frac_part.limit_denominator(4096).denominator
    p = round(float(frac_part) * q)
    err_add = p                     # fraction accumulator add per sample
    thresh = q                      # accumulated fraction that selects the long interval
    wrapper.write_text(f'.const pcm_end_ticks = {result["n_samples"]}\n'
                       f'.const EVENT_COUNT = {result["events"]}\n'
                       f'.const D418_MODE = ${d418_mode:02x}\n'
                       f'.const SAMPLE_LATCH = ${tick - 1 & 0xff:02x}\n'
                       f'.const ERR_ADD_LO = ${err_add & 0xff:02x}\n'
                       f'.const ERR_ADD_HI = ${err_add >> 8 & 0xff:02x}\n'
                       f'.const THRESH_LO = ${thresh & 0xff:02x}\n'
                       f'.const THRESH_HI = ${thresh >> 8 & 0xff:02x}\n'
                       f'.const LONG_INTERVAL = {whole + 1}\n'
                       f'.const SHORT_INTERVAL = {whole}\n'
                       f'#import "{(HERE / "sidtrace_player.asm").resolve()}"\n'
                       f'#import "{(out / "data.asm").resolve()}"\n')
    prg = out / "sidtrace.prg"
    compiled = subprocess.run(
        [str(Path.home() / ".local/bin/kickass"), str(wrapper.resolve()),
         "-o", str(prg.resolve()), "-symbolfile"],
        text=True, capture_output=True, timeout=60)
    (out / "build.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode or "ERROR IN ASSERTION" in compiled.stdout:
        raise RuntimeError(f"Assembler failed; inspect {out / 'build.log'}")
    labels = {key: int(value, 16) for key, value in
              __import__("re").findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",
                                       (out / "sidtrace.sym").read_text())}
    receipt = {
        "name": result["name"], "window_s": list(result["window"]),
        "d418_mode": f"${d418_mode:02x}",
        "tick_cycles": TICK_CYCLES, "rate_hz": round(RATE, 3),
        "program": str(prg.resolve()), "program_sha256": hashlib.sha256(prg.read_bytes()).hexdigest(),
        "program_bytes": prg.stat().st_size, "program_end": labels["program_end"],
        "samples": result["n_samples"], "duration_s": result["n_samples"] / result["rate_hz"],
        "digi_writes_resampled": result["digi_writes"], "register_events": result["events"],
        "resample": "hold staircase -> 65-tap fir -> tick grid",
        "tick50_count": round(result["n_samples"] / result["rate_hz"] * 50),
    }
    (out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--window", type=float, nargs=2, default=(1.0, 13.0),
                        metavar=("START_S", "END_S"))
    parser.add_argument("--name", default="passage")
    parser.add_argument("--out", type=Path, default=HERE / "results/sidtrace-poc")
    args = parser.parse_args()
    rows = parse_dump(args.dump)
    result = extract(rows, tuple(args.window), args.name)
    receipt = build(result, args.out)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
