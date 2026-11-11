"""Load the bounded MOD demo's reusable sample banks and SID recipes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


DEFAULT_LIBRARY = Path(__file__).resolve().parent / "instruments/cream-of-the-earth"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Instrument file escapes its library: {name}")
    return path


def sample_bytes(path: Path) -> bytes:
    """Sample includes contain only byte data, never executable instructions."""
    values = []
    for number, original in enumerate(path.read_text().splitlines(), 1):
        line = original.split("//", 1)[0].strip()
        if not line:
            continue
        if not line.startswith(".byte "):
            raise ValueError(f"Expected only .byte data at {path}:{number}")
        try:
            values.extend(int(token.strip().replace("$", "0x"), 0)
                          for token in line[6:].split(","))
        except ValueError as error:
            raise ValueError(f"Invalid sample byte at {path}:{number}") from error
    try:
        return bytes(values)
    except ValueError as error:
        raise ValueError(f"Sample value outside 0..255: {path}") from error


def load_library(directory: Path = DEFAULT_LIBRARY) -> dict:
    root = directory.resolve()
    manifest = root / "library.json"
    document = json.loads(manifest.read_text())
    if document["format_version"] != 1:
        raise ValueError("Unsupported instrument library format")
    files, instruments = [manifest], {}
    for name in document["instruments"]:
        path = local_file(root, name)
        item = json.loads(path.read_text())
        identifier = item["source_instrument"]
        if type(identifier) is not int or not 1 <= identifier <= 31 or identifier in instruments:
            raise ValueError(f"Invalid or duplicate instrument number: {path}")
        files.append(path)
        if item["kind"] == "sample":
            data_path = local_file(root, item["asm"])
            data = sample_bytes(data_path)
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"Sample bank differs from its descriptor: {path}")
            item = {**item, "asm_path": data_path, "data": data}
            files.append(data_path)
        elif item["kind"] == "sid":
            if item["program"] not in {"pulse", "triangle", "triangle-sweep", "noise-then-triangle-sweep", "noise"}:
                raise ValueError(f"Unsupported SID recipe: {path}")
            if item["rest_control"] != 0x19:
                raise ValueError("This player requires triangle + TEST + gate at rest ($19)")
            if not isinstance(item["sustain"], int) or not 0 <= item["sustain"] <= 15:
                raise ValueError(f"Invalid sustain level: {path}")
            if not 0 <= item["rms_gate_ratio"] <= 1:
                raise ValueError(f"Invalid source-tail threshold: {path}")
            if item["program"] in {"pulse", "triangle"}:
                analysis = item["pitch_analysis"]
                if analysis.get("region", "loop_if_present") not in {"attack", "loop_if_present"}:
                    raise ValueError(f"Unsupported pitch analysis region: {path}")
                low, high = analysis["period_band_samples"]
                if not (0 < low < high < analysis["sample_count"] and analysis["upsample"] > 0):
                    raise ValueError(f"Invalid pitch analysis range: {path}")
                if item["program"] == "pulse" and (
                        not 0 <= item["pulse_width"] <= 4095 or item["control"] != 0x41):
                    raise ValueError(f"Unsupported pulse state: {path}")
                if item["program"] == "triangle" and item["control"] != 0x11:
                    raise ValueError(f"Unsupported triangle state: {path}")
            else:
                if item["duration_s"] <= 0:
                    raise ValueError(f"Invalid percussion duration: {path}")
                if "noise" in item["program"] and (item["noise_divisor"] <= 0 or item["noise_control"] != 0x81):
                    raise ValueError(f"Invalid noise recipe: {path}")
                if "triangle" in item["program"] and not (
                        item["base_hz"] > 0 and item["reference_period"] > 0
                        and item["sweep_depth"] >= 0 and item["sweep_decay_s"] > 0
                        and item["triangle_control"] == 0x11):
                    raise ValueError(f"Invalid triangle sweep: {path}")
        else:
            raise ValueError(f"Unsupported instrument kind: {path}")
        instruments[identifier] = item
    if not instruments:
        raise ValueError("The instrument library is empty")
    return {"directory": root, "source": document["source"], "instruments": instruments,
            "source_sha256": {str(path.relative_to(root)): digest(path) for path in files}}


def receipt(library: dict) -> dict:
    return {"directory": str(library["directory"]), "format_version": 1,
            "instrument_count": len(library["instruments"]),
            "sample_instruments": sorted(i for i, item in library["instruments"].items() if item["kind"] == "sample"),
            "sid_instruments": sorted(i for i, item in library["instruments"].items() if item["kind"] == "sid"),
            "source": library["source"], "source_sha256": library["source_sha256"],
            "scope": "Instrument definitions only. Notes, track allocation and tracker timing remain in the arrangement. SID recipes compile on the host; sample includes assemble into reusable banks."}
