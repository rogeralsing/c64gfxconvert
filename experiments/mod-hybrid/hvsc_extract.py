"""Capture real HVSC players in VSID and retain independent voice note macros.

SID files are executable music players, not a common instrument-bank format.
This importer preserves the observed voice register sequence and source timing.
It rejects filter, sync and ring dependencies rather than silently removing them.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

import numpy as np

from vice_profile import PAL_CLOCK, PROFILE, vice_command

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "sources/sid-examples/hvsc"
OUTPUT = HERE / "results/rebuild/hvsc-hybrid/source-traces"
SOURCE_MANIFEST = HERE / "sources/hvsc.source.json"
EXTRACTOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
STRICT_NOTE_BOUNDARIES = True


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_sources(directory: Path = SOURCE, names: tuple[str, ...] | None = None) -> list[dict]:
    """Fetch hash-pinned official inputs; never overwrite mismatched local work."""
    manifest = json.loads(SOURCE_MANIFEST.read_text())
    available = {entry["name"]: entry for entry in manifest["sources"]}
    requested = tuple(available) if names is None else names
    unknown = set(requested) - available.keys()
    if unknown:
        raise ValueError(f"Unknown HVSC source: {sorted(unknown)}")
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for name in requested:
        record = {k: v for k, v in available[name].items() if k != "name"}
        path = directory / f"{name}.sid"
        if path.exists():
            raw = path.read_bytes()
        else:
            request = urllib.request.Request(record["source_url"],
                                             headers={"User-Agent": "c64-mod-hybrid/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read(int(record["bytes"]) + 1)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError(f"HVSC source identity mismatch: {path}")
        if not path.exists():
            pending = path.with_suffix(".sid.tmp")
            pending.write_bytes(raw)
            pending.replace(path)
        receipt = path.with_suffix(".source.json")
        if receipt.exists():
            old = json.loads(receipt.read_text())
            if old.get("sha256") != record["sha256"] or old.get("bytes") != record["bytes"]:
                raise ValueError(f"HVSC receipt identity mismatch: {receipt}")
        else:
            receipt.write_text(json.dumps(record, indent=2) + "\n")
        results.append(record)
    return results


def read_trace(path: Path) -> np.ndarray:
    rows, clock = [], 0
    with path.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                delta, register, value = map(int, fields)
            except ValueError:
                continue
            clock += delta
            if not 0 <= register < 32:
                raise ValueError("This instrument import requires one SID chip")
            if register <= 24:
                rows.append((clock, register, value))
    return np.asarray(rows, dtype=np.int64).reshape(-1, 3)


def capture_sid(source: Path, out: Path, subtune: int = 1, seconds: float = 30) -> dict:
    fetch_sources(source.parent, (source.stem,))
    provenance = json.loads(source.with_suffix(".source.json").read_text())
    if sha(source) != provenance["sha256"]:
        raise ValueError("HVSC source differs from its download receipt")
    if not 1 <= subtune <= provenance["songs"]:
        raise ValueError("Source subtune is outside the SID header range")
    out.mkdir(parents=True, exist_ok=True)
    trace, receipt_path = out / "registers.txt", out / "capture.json"
    identity = {"source_sha256": provenance["sha256"], "subtune": subtune,
                "seconds": seconds, "profile": dict(PROFILE)}
    if receipt_path.exists() and trace.exists():
        previous = json.loads(receipt_path.read_text())
        if (all(previous.get(k) == v for k, v in identity.items())
                and previous.get("trace_sha256") == sha(trace)):
            return previous
    command = vice_command()
    command[0] = "/opt/homebrew/bin/vsid"
    command += ["-console", "-keepenv", "-tune", str(subtune), "-seed", "1",
                "-sounddev", "dump", "-soundarg", str(trace.resolve()), "-warp",
                "-limitcycles", str(round(seconds * PAL_CLOCK)), str(source.resolve())]
    completed = subprocess.run(command, text=True, errors="replace", capture_output=True,
                               timeout=seconds + 45)
    log = completed.stdout + completed.stderr
    (out / "vsid.log").write_text(log)
    rows = read_trace(trace)
    # VICE reports a deliberate cycle-limit termination as exit 1. A useful
    # trace and the explicit stop message distinguish it from an emulator error.
    limited = "cycle limit" in log.lower()
    if completed.returncode and not limited:
        raise RuntimeError(f"VSID failed; inspect {out / 'vsid.log'}")
    if len(rows) < 100 or rows[-1, 0] < round((seconds - 2) * PAL_CLOCK):
        raise ValueError("Incomplete source SID register capture")
    if "MOS8580 + digi boost" not in log:
        raise ValueError("VSID did not confirm the fixed digiboost model")
    receipt = identity | {"source": provenance, "command": command,
                          "returncode": completed.returncode,
                          "trace_sha256": sha(trace), "register_writes": len(rows),
                          "last_cycle": int(rows[-1, 0]),
                          "scope": "Actual source player execution in VSID. Source timing is observed, not assumed to be 50 Hz. Header model is overridden deliberately to the one supported playback profile."}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def extract_patches(trace: Path, capture: dict, limit: int = 20) -> list[dict]:
    rows = read_trace(trace)
    snapshots = np.zeros((len(rows), 25), dtype=np.int64)
    state = np.zeros(25, dtype=np.int64)
    onsets = [[] for _ in range(3)]
    for index, (cycle, register, value) in enumerate(rows):
        previous = int(state[register])
        state[register] = value
        snapshots[index] = state
        if register in (4, 11, 18):
            if value & 1 and not value & 8 and value & 0xf0 and (not previous & 1 or previous & 8):
                onsets[(register - 4) // 7].append(index)
    candidates = []
    for voice in range(3):
        base = 7 * voice
        starts = onsets[voice]
        voice_indices = np.flatnonzero((rows[:, 1] >= base) & (rows[:, 1] < base + 7))
        if not len(voice_indices):
            continue
        # One player's update writes frequency low/high and control/ADSR in a
        # short burst. Interpret only the settled burst state as a note pitch;
        # every original store remains available separately in raw events.
        divisions = np.r_[0, np.flatnonzero(np.diff(rows[voice_indices, 0]) > 1000) + 1,
                          len(voice_indices)]
        batches = [(int(voice_indices[a]), int(voice_indices[b - 1]))
                   for a, b in zip(divisions[:-1], divisions[1:])]
        batch_ends = np.asarray([end for _, end in batches])
        for number, start_index in enumerate(starts):
            start_cycle = int(rows[start_index, 0])
            next_cycle = (int(rows[starts[number + 1], 0]) if number + 1 < len(starts)
                          else int(rows[-1, 0]))
            end_cycle = min(next_cycle - round(.003 * PAL_CLOCK),
                            start_cycle + round(.8 * PAL_CLOCK))
            first_batch = int(np.searchsorted(batch_ends, start_index))
            initial_index = batches[first_batch][1]
            first_state = snapshots[initial_index, base:base + 7]
            initial_control = int(first_state[4])
            if not initial_control & 1 or initial_control & 8 or initial_control & 0x80:
                continue
            base_frequency = int(first_state[0] + 256 * first_state[1])
            if not 100 <= base_frequency <= 50000:
                continue
            pitch_boundary = False
            frame_indices = []
            for batch_start, batch_end in batches[first_batch:]:
                cycle = int(rows[batch_end, 0])
                if cycle >= end_cycle:
                    break
                s = snapshots[batch_end, base:base + 7]
                frequency = int(s[0] + 256 * s[1])
                if cycle - start_cycle >= round(.04 * PAL_CLOCK):
                    # A held gate does not mean a held note. Stop before the
                    # donor's next legato melody pitch instead of importing it
                    # as an instrument pitch envelope. Permit small vibrato.
                    if not base_frequency / 2**(50/1200) <= frequency <= base_frequency * 2**(50/1200):
                        end_cycle = min(end_cycle, int(rows[batch_start, 0]))
                        pitch_boundary = True
                        break
                frame_indices.append(batch_end)
            if end_cycle - start_cycle < round(.075 * PAL_CLOCK):
                continue
            end_index = int(np.searchsorted(rows[:, 0], end_cycle, side="right"))
            section = rows[start_index:end_index]
            states = snapshots[start_index:end_index]
            controls = states[:, base + 4]
            # Ring modulation and oscillator sync depend on the previous voice.
            # A shared filter is also an instrument dependency, not a voice byte.
            if np.any(controls & 6) or np.any(((states[:, 23] & (1 << voice)) != 0) & ((states[:, 24] & 0x70) != 0)):
                continue
            if voice == 2 and np.any(((states[:, 24] & 0x80) != 0) & ((states[:, 23] & 4) == 0)):
                continue
            relevant = section[(section[:, 1] >= base) & (section[:, 1] < base + 7)]
            if not len(relevant):
                continue
            # Preserve exact source write order, including repeated writes.
            events = [[int(c - start_cycle), int(r - base), int(v)] for c, r, v in relevant]
            initial = [int(v) for v in first_state]
            pre_start = int(np.searchsorted(rows[:, 0], start_cycle - round(.06 * PAL_CLOCK)))
            pre = rows[pre_start:start_index]
            prelude = [[int(c - start_cycle), int(r - base), int(v)] for c, r, v in pre
                       if base <= r < base + 7]
            # Source update timestamps remain exact. The first settled state
            # is the note's time-zero frame, with the actual settlement delay
            # retained separately; downstream resampling must be explicit.
            frames, last = [], None
            for frame_number, index in enumerate(frame_indices):
                cycle, reg, _ = rows[index]
                s = snapshots[index, base:base + 7]
                effective_cycle = int(cycle - start_cycle) if frame_number else 0
                frame = {"cycle": effective_cycle,
                         "time_s": effective_cycle / PAL_CLOCK,
                         "source_settled_cycle": int(cycle - start_cycle),
                         "frequency": int(s[0] + 256 * s[1]),
                         "frequency_ratio": float((s[0] + 256 * s[1]) / base_frequency),
                         "pulse": int(s[2] + 256 * (s[3] & 15)),
                         "control": int(s[4]), "ad": int(s[5]), "sr": int(s[6])}
                values = tuple(frame[k] for k in ("frequency", "pulse", "control", "ad", "sr"))
                if values != last:
                    frames.append(frame)
                    last = values
            duration = (end_cycle - start_cycle) / PAL_CLOCK
            waveforms = sorted({int(v & 0xf0) for v in controls if v & 0xf0})
            if not frames or not any(w in waveforms for w in (0x10, 0x20, 0x40)):
                continue
            # Prefer one-note tonal plucks with low source sustain. This ranks
            # importability only, never perceptual similarity to a MOD sample.
            sustain = int(np.median(states[:, base + 6] >> 4))
            score = (15 - sustain) + min(duration, .4) * 20 - max(0, len(waveforms) - 2) * 2
            patch_id = f"{Path(capture['source']['hvsc_path']).stem.lower()}-s{capture['subtune']}-v{voice + 1}-n{number:03d}"
            candidates.append({"id": patch_id, "source": capture["source"],
                               "extractor_sha256": EXTRACTOR_SHA256,
                               "strict_note_boundaries": STRICT_NOTE_BOUNDARIES,
                               "source_subtune": capture["subtune"], "source_voice": voice + 1,
                               "source_onset_cycle": start_cycle, "base_frequency": base_frequency,
                               "base_frequency_hz": base_frequency * PAL_CLOCK / 2**24,
                               "duration_s": duration, "initial_registers": initial,
                               "prelude_events": prelude, "events": events, "frames": frames,
                               "clipped_at_donor_pitch_change": pitch_boundary,
                               "waveforms": waveforms, "source_sustain": sustain,
                               "importability_score": score,
                               "trace_sha256": capture["trace_sha256"],
                               "dependencies": {"sync": False, "ring": False, "filter": False},
                               "scope": "One observed note program, bounded before donor legato pitch changes beyond50cents after40ms. Pitch base is the first settled source voice-write burst. Frames snapshot complete bursts; raw stores retain original order/timing. Source note length, ADSR and gate release remain observed data, not a universal instrument definition."})
    selected, identities = [], set()
    for patch in sorted(candidates, key=lambda p: p["importability_score"], reverse=True):
        # Keep different waveform/ADSR/pulse programs, not many copies of notes
        # from the same riff at different pitches.
        signature = (patch["source_voice"], tuple(patch["waveforms"]),
                     patch["initial_registers"][5], patch["initial_registers"][6],
                     patch["initial_registers"][2] // 32,
                     round(patch["duration_s"] * 10))
        if signature in identities:
            continue
        identities.add(signature)
        selected.append(patch)
        if len(selected) >= limit:
            break
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", default=["Wizball", "Commando", "Monty_on_the_Run", "Cybernoid_II", "Last_Ninja_2", "Shades_filter_corrected", "Raw_Recruit", "Pulse", "Hawkeye", "Cybernoid", "Great_Giana_Sisters"])
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    fetch_sources(SOURCE, tuple(args.sources))
    def process(name: str) -> dict:
        tune = 8 if name == "Wizball" else 1
        source = SOURCE / f"{name}.sid"
        folder = args.out / name
        receipt = capture_sid(source, folder, tune, args.seconds)
        patches = extract_patches(folder / "registers.txt", receipt, limit=10)
        result = {"source": name, "capture": receipt, "patches": patches}
        (folder / "patches.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"{name}: {len(patches)} independent tonal note macros", flush=True)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(process, args.sources))
    catalog = {"schema_version": 2, "profile": dict(PROFILE),
               "extractor_sha256": EXTRACTOR_SHA256,
               "strict_note_boundaries": STRICT_NOTE_BOUNDARIES,
               "patches": [p for r in results for p in r["patches"]],
               "sources": [{"source": r["source"], "patches": len(r["patches"]),
                            "trace_sha256": r["capture"]["trace_sha256"]} for r in results],
               "scope": "Source register trajectories from real HVSC players. No note macro is yet ranked against target audio; filter/sync/ring dependent notes excluded."}
    pending = args.out / "catalog.tmp.json"
    pending.write_text(json.dumps(catalog, indent=2) + "\n")
    pending.replace(args.out / "catalog.json")
    print(json.dumps({"catalog": str((args.out / 'catalog.json').resolve()),
                      "patches": len(catalog["patches"])}, indent=2))


if __name__ == "__main__":
    main()
