"""Shared build, source verification and VICE capture for the native SID mixer."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
MOD = HERE.parent / "mod-hybrid"
CLOCK, PERIOD, PAULA = 985248, 126, 3546894.6
sys.path.insert(0, str(MOD))
from mod_reader import load_mod
from timeline import build_timeline

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

def profile():
    path = HERE.parent / "mod-hybrid/vice_profile.py"
    spec = importlib.util.spec_from_file_location("voice_sampler_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def assemble(name: str, out: Path) -> dict:
    source = HERE / f"{name}.asm"
    target = out / f"{name}.asm"
    shutil.copyfile(source, target)
    command = [str(Path.home() / ".local/bin/kickass"), str(target.resolve()),
               "-o", str((out / f"{name}.prg").resolve()), "-symbolfile"]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / f"{name}-build.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    sym = out / f"{name}.sym"
    labels = {k: int(v, 16) for k, v in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", sym.read_text())}
    prg = out / f"{name}.prg"
    return {"program": str(prg.resolve()), "symbols": labels, "bytes": prg.stat().st_size,
            "program_sha256": digest(prg), "source_sha256": digest(source)}

def capture(build: dict, out: Path, duration: float, audio: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    labels = build["symbols"]
    monitor = out / "capture.mon"
    stats = out / "stats.bin"
    stats.unlink(missing_ok=True)
    monitor.write_text(f'load "{build["program"]}" 0\n'
                       f'break exec ${labels["done"]:04x}\n'
                       f'g ${labels["start"]:04x}\n'
                       'step 20000\n'
                       f'bsave "{stats.resolve()}" 0 $0002 $000d\nquit\n')
    settings = profile()
    mode = "audio" if audio else "registers"
    media = out / ("raw.wav" if audio else "registers.txt")
    media.unlink(missing_ok=True)
    command = settings.vice_command() + ["-console", "-seed", "1", "-initbreak", "ready",
        "-moncommands", str(monitor.resolve()), "-limitcycles", str(round((duration + 15) * CLOCK)),
        "-sounddev", "wav" if audio else "dump", "-soundarg", str(media.resolve())]
    command += ["+warp", "-speed", "100"] if audio else ["-warp"]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=duration + 60)
    (out / f"{mode}.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not stats.exists():
        raise RuntimeError(f"VICE {mode} did not reach the completion breakpoint; inspect {out}")
    return {"program_sha256": build["program_sha256"], "profile": settings.PROFILE,
            "command": command, "stats_hex": stats.read_bytes().hex(),
            "stats_file": str(stats.resolve()), "media": str(media.resolve()),
            "media_sha256": digest(media)}

def source_mod(source: dict, out: Path) -> dict:
    slug = source.get("title_slug", "")
    cached = MOD / "sources" / f"{slug}.mod"
    path = cached if slug and cached.exists() else out / "source.mod"
    if not path.exists():
        with urllib.request.urlopen(source.get("download_url") or source["source_url"], timeout=45) as response:
            data = response.read()
        if len(data) != source["bytes"]:
            raise ValueError("Downloaded MOD has the wrong size")
        path.write_bytes(data)
    if path.stat().st_size != source["bytes"] or digest(path) != source["sha256"]:
        raise ValueError("MOD differs from the instrument library's source receipt")
    if path.parent == out:
        save(path.with_suffix(".source.json"), source)
    return load_mod(path)

def audio(receipt: dict, proof: dict, pcm: dict, out: Path) -> dict:
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[8:10], "little") != pcm["frames"] or stats[6]:
        raise ValueError("Hybrid audio run missed buffers")
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    if rate != 22050 or raw.shape[1] != 1:
        raise ValueError("Expected fixed-profile mono 22050 Hz audio")
    start = round(proof["first_latch_cycle"] * rate / CLOCK)
    count = round(pcm["duration_s"] * rate)
    signal = raw[start:start + count, 0].copy()
    if len(signal) != count: raise ValueError("Incomplete hybrid recording")
    signal -= signal.mean(); peak = float(np.max(np.abs(signal)))
    if peak < .001: raise ValueError("Hybrid recording is silent")
    gain = min(8.0, .92 / peak)
    sf.write(out / "hybrid.wav", signal * gain, rate, subtype="PCM_16")
    result = {"frames": count, "duration_s": count / rate, "sample_rate": rate,
              "profile": receipt["profile"], "generated_frames": pcm["frames"], "underruns": 0,
              "raw_peak": peak, "raw_rms": float(np.std(signal)), "listening_gain": gain,
              "output_sha256": digest(out / "hybrid.wav"),
              "processing": "Actual VICE WAV, clock-anchored crop, DC removal and one constant gain. No host mixing, EQ, alignment, time stretching or dynamics."}
    save(out / "audio-check.json", result)
    return result
