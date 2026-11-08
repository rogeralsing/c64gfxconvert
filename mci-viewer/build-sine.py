#!/usr/bin/env python3
"""Build the stock PAL C64 MCI sine player from prepared strips and row maps."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


DATA_SIZES = {"source-a.bin": 12480, "source-b.bin": 12480,
              "screen-a.bin": 1000, "screen-b.bin": 1000,
              "colors.bin": 1000, "background.bin": 1}
OPTIONAL_SIZES = {"bitmap-a.bin": 8000, "bitmap-b.bin": 8000}
MAX_CHANGED_ROWS = 31


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_data(directory):
    payloads = {name: (directory / name).read_bytes() for name in DATA_SIZES}
    for name, expected in DATA_SIZES.items():
        if len(payloads[name]) != expected:
            raise ValueError(f"{name} must contain exactly {expected} bytes.")
    if payloads["background.bin"][0] > 15 or any(color > 15 for color in payloads["colors.bin"]):
        raise ValueError("Background and Color RAM must use C64 indices 0–15.")
    for row in range(1, 25, 2):
        for name in ("screen-a.bin", "screen-b.bin", "colors.bin"):
            data = payloads[name]
            if data[row * 40:(row + 1) * 40] != data[(row - 1) * 40:row * 40]:
                raise ValueError(f"{name} must retain each palette across its 16-line band.")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("format") != "MCI sine source strips v1":
        raise ValueError("Unsupported prepared source-strip format.")
    for name, data in payloads.items():
        if manifest.get("files", {}).get(name, {}).get("sha256") != digest(data):
            raise ValueError(f"{name} does not match the prepared-data manifest.")
    protected = [directory / name for name in DATA_SIZES] + [manifest_path]
    for phase in ("a", "b"):
        name = f"bitmap-{phase}.bin"
        path = directory / name
        if not path.exists():
            continue
        bitmap = path.read_bytes()
        if len(bitmap) != OPTIONAL_SIZES[name]:
            raise ValueError(f"{name} must contain exactly 8000 bytes.")
        if manifest.get("files", {}).get(name, {}).get("sha256") != digest(bitmap):
            raise ValueError(f"{name} does not match the prepared-data manifest.")
        source = payloads[f"source-{phase}.bin"]
        for y in range(200):
            for column in range(40):
                tile = y // 8 * 40 + column
                index = (y // 16 * 40 + column) * 24 + (y & 15) + 4
                if bitmap[tile * 8 + y % 8] != source[index]:
                    raise ValueError(f"{name} differs from its zero-displacement source strips.")
        protected.append(path)
    return payloads, manifest, protected


def read_geometry(directory):
    offsets = (directory / "frame-offsets.bin").read_bytes()
    records = (directory / "row-maps.rle").read_bytes()
    if len(offsets) != 480:
        raise ValueError("frame-offsets.bin must contain 240 little-endian 16-bit offsets.")
    if not records or 0xE180 + len(offsets) + len(records) > 0xF500:
        raise ValueError("Geometry must fit between $e180 and the runtime at $f500.")
    starts = [int.from_bytes(offsets[index:index + 2], "little") for index in range(0, 480, 2)]
    if starts[0] != 0 or any(left >= right for left, right in zip(starts, starts[1:])):
        raise ValueError("Geometry offsets must start at zero and increase strictly.")
    maps = []
    maximum_runs = 0
    for frame, start in enumerate(starts):
        boundary = starts[frame + 1] if frame < 239 else len(records)
        if start >= len(records) or boundary > len(records) or (boundary - start) % 2:
            raise ValueError(f"Frame {frame} points outside complete geometry records.")
        row_map = []
        position = start
        runs = 0
        while position < boundary:
            end = records[position]
            raw_displacement = records[position + 1]
            displacement = raw_displacement if raw_displacement < 128 else raw_displacement - 256
            if not len(row_map) < end <= 200 or not -4 <= displacement <= 4:
                raise ValueError(f"Frame {frame} contains invalid row or displacement bounds.")
            for y in range(len(row_map), end):
                source_y = y + displacement
                strip_row = (y & 15) + 4 + displacement
                if not 0 <= source_y < 200 or not 0 <= strip_row < 24:
                    raise ValueError(f"Frame {frame}, row {y} reads outside the source strips.")
                row_map.append(source_y)
            runs += 1
            position += 2
            if end == 200:
                break
        if len(row_map) != 200 or position != boundary:
            raise ValueError(f"Frame {frame} must finish at row 200 with no trailing records.")
        if any(left > right for left, right in zip(row_map, row_map[1:])):
            raise ValueError(f"Frame {frame} reverses source-row order.")
        maps.append(row_map)
        maximum_runs = max(maximum_runs, runs)
    if maps[0] != list(range(200)):
        raise ValueError("The first geometry frame must start with zero displacement.")
    changed = [sum(left != right for left, right in zip(maps[index - 1], maps[index]))
               for index in range(240)]
    if max(changed) > MAX_CHANGED_ROWS:
        raise ValueError(f"Geometry exceeds the verified {MAX_CHANGED_ROWS}-row copy budget per phase.")
    metadata = {"frames": 240, "height": 200, "maximum_runs_per_frame": maximum_runs,
                "maximum_changed_rows": max(changed), "offset_bytes": len(offsets),
                "record_bytes": len(records)}
    return {"frame-offsets.bin": offsets, "row-maps.rle": records}, metadata


def build(data_directory, geometry_directory, output, assembler, force=False):
    data_directory = data_directory.resolve()
    geometry_directory = geometry_directory.resolve()
    output = output.resolve()
    assembler = assembler.expanduser().resolve()
    if output.suffix.lower() != ".prg":
        raise ValueError("The output must use a .prg extension.")
    payloads, source_manifest, protected = read_data(data_directory)
    geometry, geometry_metadata = read_geometry(geometry_directory)
    payloads.update(geometry)
    player = Path(__file__).with_name("sine-player.asm").resolve()
    protected.extend([player, assembler, *(geometry_directory / name for name in geometry)])
    targets = [output, output.with_suffix(".sym"), output.with_suffix(".vs"), output.with_suffix(".json")]
    protected_paths = {path.resolve() for path in protected}
    for target in targets:
        if target.resolve() in protected_paths:
            raise ValueError(f"Build artifacts must not replace an input file: {target}.")
        if target.exists() and not force:
            raise FileExistsError(f"Refusing to replace {target}; use --force for build artifacts.")
    with tempfile.TemporaryDirectory(prefix="c64-mci-sine-") as temporary:
        stage = Path(temporary)
        for name, data in payloads.items():
            (stage / name).write_bytes(data)
        shutil.copyfile(player, stage / "player.asm")
        subprocess.run([str(assembler), "player.asm", "-o", "image.prg", "-odir", str(stage),
                        "-symbolfile", "-vicesymbols"], cwd=stage, check=True, timeout=60)
        program = (stage / "image.prg").read_bytes()
        if len(program) < 2 or program[:2] != b"\x01\x08":
            raise ValueError("Expected a BASIC-started PRG loading at $0801.")
        loaded_end = 0x0801 + len(program) - 2
        if loaded_end > 0xD000:
            raise ValueError("The staged PRG must finish before the C64 I/O area at $d000.")
        receipt = {
            "format": "standalone stock PAL C64 MCI sine PRG",
            "source": source_manifest.get("source"),
            "source_sha256": source_manifest.get("source_sha256"),
            "program_sha256": digest(program), "player_sha256": digest(player.read_bytes()),
            "bytes": len(program), "staged_load_address": "$0801",
            "staged_end_exclusive": f"${loaded_end:04x}",
            "display": {"width": 320, "height": 200, "phase_count": 2,
                        "phase_b_offset_pixels": 1, "phase_rate_hz": 50, "motion_rate_hz": 25},
            "geometry": geometry_metadata,
            "palette_refit": source_manifest.get("zero_wave_metrics"),
            "memory": {"screen_a": "$0400", "bitmap_a": "$2000",
                       "screen_b": "$4400", "bitmap_b": "$6000",
                       "copy_code_a": "$0800", "copy_code_b": "$4800",
                       "source_a": "$8000", "source_b": "$b0c0",
                       "geometry": "$e180", "runtime": "$f500"},
            "inputs": {name: {"bytes": len(data), "sha256": digest(data)}
                       for name, data in payloads.items()},
        }
        artifacts = [program, (stage / "player.sym").read_bytes(), (stage / "player.vs").read_bytes(),
                     (json.dumps(receipt, indent=2) + "\n").encode()]
        output.parent.mkdir(parents=True, exist_ok=True)
        for target, artifact in zip(targets, artifacts):
            with target.open("wb" if force else "xb") as stream:
                stream.write(artifact)
    print(f"Created {output} ({len(program):,} bytes; {geometry_metadata['maximum_changed_rows']} changed rows maximum)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, default=Path.home() / ".local/bin/kickass")
    parser.add_argument("--force", action="store_true", help="replace existing build artifacts")
    args = parser.parse_args()
    build(args.data_dir, args.geometry_dir, args.output, args.assembler, args.force)
