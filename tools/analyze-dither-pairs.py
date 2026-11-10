#!/usr/bin/env python3
"""Count canonical vertical C64 color pairs and their spatial neighbors."""

import argparse
import base64
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from c64_palette import load_palette


COLOR_NAMES = ["Black", "White", "Red", "Cyan", "Purple", "Green", "Blue", "Yellow",
               "Orange", "Brown", "Light red", "Dark gray", "Medium gray", "Light green",
               "Light blue", "Light gray"]


def lightness(luminance):
    values = np.asarray(luminance)
    return np.where(values > 216 / 24389, 116 * np.cbrt(values) - 16, values * 24389 / 27)


def srgb_to_linear(rgb):
    srgb = np.asarray(rgb, dtype=np.float64) / 255
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def palette_metadata(palette):
    linear = srgb_to_linear(palette)
    luminances = linear @ np.array([0.2126, 0.7152, 0.0722])
    lightnesses = lightness(luminances)
    return [{"index": i, "name": COLOR_NAMES[i], "rgb": rgb.tolist(),
             "hex": "#" + "".join(f"{int(channel):02X}" for channel in rgb),
             "luminance": float(luminances[i]), "lightness": float(lightnesses[i])}
            for i, rgb in enumerate(palette)]


def canonical_lookup(metadata):
    table = np.empty((16, 16), dtype=np.uint16)
    for top in range(16):
        for bottom in range(16):
            delta = metadata[top]["lightness"] - metadata[bottom]["lightness"]
            first, second = ((min(top, bottom), max(top, bottom)) if abs(delta) <= 1
                             else ((top, bottom) if delta < 0 else (bottom, top)))
            table[top, bottom] = first * 16 + second
    return table


def pair_id(code):
    return f"{int(code) // 16}-{int(code) % 16}"


def count_pairs(codes):
    counts = np.bincount(codes.ravel(), minlength=256)
    return {pair_id(code): int(count) for code, count in enumerate(counts) if count}


def index_image(path, palette):
    with Image.open(path) as image:
        if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            raise ValueError(f"{path}: unsupported image mode {image.mode}; use an 8-bit image.")
        rgba = np.asarray(image.convert("RGBA"))
    height, width = rgba.shape[:2]
    if height < 2 or width < 2 or width % 2:
        raise ValueError(f"{path}: expected even width and at least two rows.")
    if np.any(rgba[:, :, 3] != 255):
        raise ValueError(f"{path}: transparency is not supported; supply opaque C64 pixels.")
    rgb = rgba[:, :, :3]
    if not np.array_equal(rgb[:, ::2], rgb[:, 1::2]):
        raise ValueError(f"{path}: horizontal 2x1 pixel pairs are not identical.")
    rgb = rgb[:, ::2].astype(np.uint32)
    packed = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    indexed = np.full(packed.shape, 255, dtype=np.uint8)
    for i, color in enumerate(palette):
        value = (int(color[0]) << 16) | (int(color[1]) << 8) | int(color[2])
        indexed[packed == value] = i
    unknown = np.unique(packed[indexed == 255])
    if len(unknown):
        examples = ", ".join(f"#{int(value):06X}" for value in unknown[:5])
        raise ValueError(f"{path}: {len(unknown)} colors are outside the palette ({examples}). Snap colors first.")
    return indexed, [width, height]


def analyze_image(indexed, lookup):
    top, bottom = indexed[:-1], indexed[1:]
    codes = lookup[top, bottom]
    counts = count_pairs(codes)
    canonical = top == codes // 16
    forward = count_pairs(codes[canonical])
    reverse = count_pairs(codes[~canonical])
    orientations = {key: {"canonical": forward.get(key, 0), "reversed": reverse.get(key, 0)}
                    for key in counts}
    edge_counts = {"horizontal": Counter(), "vertical": Counter()}
    for direction, a, b in (("horizontal", codes[:, :-1], codes[:, 1:]),
                             ("vertical", codes[:-2], codes[2:])):
        edge_codes = np.minimum(a, b).astype(np.uint32) * 256 + np.maximum(a, b)
        unique, frequencies = np.unique(edge_codes, return_counts=True)
        edge_counts[direction].update({int(key): int(count) for key, count in zip(unique, frequencies)})
    edges = []
    self_adjacency = {}
    for key in sorted(set(edge_counts["horizontal"]) | set(edge_counts["vertical"])):
        a, b = key // 256, key % 256
        horizontal = edge_counts["horizontal"][key]
        vertical = edge_counts["vertical"][key]
        entry = {"horizontal": horizontal, "vertical": vertical, "count": horizontal + vertical}
        if a == b:
            self_adjacency[pair_id(a)] = entry
        else:
            edges.append({"a": pair_id(a), "b": pair_id(b), **entry})
    solid_total = int(np.count_nonzero(top == bottom))
    return {"pair_total": int(codes.size), "solid_pair_total": solid_total,
            "mixed_pair_total": int(codes.size) - solid_total, "pair_counts": counts,
            "orientation_counts": orientations,
            "phase_pair_counts": [count_pairs(codes[::2]), count_pairs(codes[1::2])],
            "edges": edges, "self_adjacency": self_adjacency}


def aggregate_images(images, metadata, min_count, min_edge_count):
    counts, canonical, reversed_counts, image_counts = Counter(), Counter(), Counter(), Counter()
    edges = {}
    self_adjacency = {}
    phase_counts = [Counter(), Counter()]
    for image in images:
        counts.update(image["pair_counts"])
        image_counts.update(image["pair_counts"].keys())
        for key, orientation in image["orientation_counts"].items():
            canonical[key] += orientation["canonical"]
            reversed_counts[key] += orientation["reversed"]
        for phase in (0, 1):
            phase_counts[phase].update(image["phase_pair_counts"][phase])
        for edge in image["edges"]:
            key = (edge["a"], edge["b"])
            entry = edges.setdefault(key, {"a": key[0], "b": key[1], "horizontal": 0, "vertical": 0, "count": 0})
            for field in ("horizontal", "vertical", "count"):
                entry[field] += edge[field]
        for key, adjacency in image["self_adjacency"].items():
            entry = self_adjacency.setdefault(key, {"horizontal": 0, "vertical": 0, "count": 0})
            for field in entry:
                entry[field] += adjacency[field]
    pairs = []
    for key, count in counts.items():
        a, b = map(int, key.split("-"))
        mixed_luminance = (metadata[a]["luminance"] + metadata[b]["luminance"]) / 2
        mixed_linear = srgb_to_linear([metadata[a]["rgb"], metadata[b]["rgb"]]).mean(axis=0)
        encoded = np.where(mixed_linear <= 0.0031308, mixed_linear * 12.92,
                           1.055 * mixed_linear ** (1 / 2.4) - 0.055)
        virtual_rgb = np.floor(np.clip(encoded, 0, 1) * 255 + 0.5).astype(np.uint8).tolist()
        pairs.append({"id": key, "colors": [a, b], "count": count, "mixed": a != b,
                      "canonical_count": canonical[key], "reversed_count": reversed_counts[key],
                      "image_count": image_counts[key], "retained": count >= min_count,
                      "virtual_rgb": virtual_rgb,
                      "virtual_hex": "#" + "".join(f"{channel:02X}" for channel in virtual_rgb),
                      "luminance": mixed_luminance,
                      "lightness": float(lightness(mixed_luminance))})
    pairs.sort(key=lambda pair: (-pair["count"], pair["id"]))
    retained = {pair["id"] for pair in pairs if pair["retained"]}
    edge_list = sorted(edges.values(), key=lambda edge: (-edge["count"], edge["a"], edge["b"]))
    for edge in edge_list:
        edge["retained"] = edge["a"] in retained and edge["b"] in retained and edge["count"] >= min_edge_count
    totals = {field: sum(image[field] for image in images)
              for field in ("pair_total", "mixed_pair_total", "solid_pair_total")}
    retained_mixed_count = sum(pair["count"] for pair in pairs if pair["mixed"] and pair["retained"])
    return {**totals, "pairs": pairs, "edges": edge_list,
            "phase_pair_counts": [dict(count) for count in phase_counts], "self_adjacency": self_adjacency,
            "pair_types": len(pairs), "mixed_pair_types": sum(pair["mixed"] for pair in pairs),
            "retained_pair_types": len(retained),
            "retained_mixed_pair_types": sum(pair["mixed"] and pair["retained"] for pair in pairs),
            "retained_mixed_occurrences": retained_mixed_count,
            "retained_mixed_share": retained_mixed_count / totals["mixed_pair_total"] if totals["mixed_pair_total"] else 0,
            "retained_edge_types": sum(edge["retained"] for edge in edge_list)}


def input_paths(args):
    if args.manifest:
        if args.inputs:
            raise ValueError("Use positional inputs or --manifest, not both.")
        document = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("images"), list):
            raise ValueError("Manifest must contain an images array.")
        paths = []
        for record in document["images"]:
            if not isinstance(record, dict) or not isinstance(record.get("output"), str) or not record["output"]:
                raise ValueError("Each manifest image needs an output path.")
            path = Path(record["output"])
            paths.append(path if path.is_absolute() else args.manifest.parent / path)
    else:
        paths = args.inputs
    if not paths:
        raise ValueError("Supply input images or --manifest.")
    return [path.resolve() for path in paths]


def write_outputs(output_dir, data):
    output_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with (output_dir / "analysis.json").open("x", encoding="utf-8") as stream:
        stream.write(serialized)
    with (output_dir / "pairs.csv").open("x", encoding="utf-8", newline="") as stream:
        fields = ["id", "top_index", "bottom_index", "count", "mixed", "canonical_count", "reversed_count", "image_count", "retained", "virtual_hex", "luminance", "lightness"]
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for pair in data["aggregate"]["pairs"]:
            writer.writerow({**{key: pair[key] for key in fields if key in pair},
                             "top_index": pair["colors"][0], "bottom_index": pair["colors"][1]})
    with (output_dir / "neighbors.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, ["a", "b", "horizontal", "vertical", "count", "retained"])
        writer.writeheader()
        writer.writerows(data["aggregate"]["edges"])
    template = Path(__file__).with_name("dither-pairs-report.html")
    if template.exists():
        # Source paths are data, including when a filename contains HTML syntax.
        embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
        report = template.read_text(encoding="utf-8").replace("__DITHER_DATA__", embedded)
        with (output_dir / "report.html").open("x", encoding="utf-8") as stream:
            stream.write(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--manifest", type=Path, help="Extractor manifest; reads each image's output path.")
    parser.add_argument("--palette", type=Path, default=Path(__file__).resolve().parents[1] / "palettes" / "peptoette-a.vpl")
    parser.add_argument("-o", "--output-dir", type=Path, required=True)
    parser.add_argument("--min-count", type=int, default=500, help="Minimum pair occurrences for the default retained graph.")
    parser.add_argument("--min-edge-count", type=int, default=50, help="Minimum contacts for the default retained graph.")
    args = parser.parse_args()
    if args.min_count < 0 or args.min_edge_count < 0:
        parser.error("Frequency thresholds must be nonnegative.")
    try:
        if args.output_dir.exists() and (not args.output_dir.is_dir() or any(args.output_dir.iterdir())):
            raise ValueError(f"Refusing to overwrite nonempty output directory: {args.output_dir}")
        palette = load_palette(args.palette)
        metadata = palette_metadata(palette)
        lookup = canonical_lookup(metadata)
        paths = input_paths(args)
        images, seen = [], {}
        for position, source in enumerate(paths, 1):
            indexed, physical_size = index_image(source, palette)
            digest = hashlib.sha256(struct.pack("!II", *indexed.shape) + indexed.tobytes()).hexdigest()
            if digest in seen:
                seen[digest]["aliases"].append({"id": position, "source": str(source)})
                continue
            image = {"id": position, "source": str(source), "aliases": [],
                     "physical_size": physical_size, "logical_size": [indexed.shape[1], indexed.shape[0]],
                     "pixels_base64": base64.b64encode(indexed.tobytes()).decode("ascii"),
                     **analyze_image(indexed, lookup)}
            images.append(image)
            seen[digest] = image
        aggregate = aggregate_images(images, metadata, args.min_count, args.min_edge_count)
        data = {"schema_version": 1, "palette": metadata,
                "method": {"palette_source": str(args.palette.resolve()), "logical_pixel_width": 2,
                           "pair_rows": [0, 1], "phase_policy": "both phases; every vertical neighbor once",
                           "adjacency_offsets": {"horizontal": [1, 0], "vertical": [0, 2]},
                           "canonical_brightness": "CIE L* from linear-sRGB Rec.709 relative luminance; ties use C64 index",
                           "virtual_color": "Equal 50/50 linear-sRGB channel mix, then sRGB encoding and nearest 8-bit rounding; relative luminance Y is measured before 8-bit rounding",
                           "tie_lightness": 1.0, "deduplicate_images": True,
                           "min_count": args.min_count, "min_edge_count": args.min_edge_count,
                           "input_count": len(paths), "unique_image_count": len(images),
                           "adjacency_caveat": "Spatial contacts include object boundaries; they do not prove an intentional gradient."},
                "images": images, "aggregate": aggregate}
        write_outputs(args.output_dir, data)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"{len(images)} unique images from {len(paths)} inputs; {aggregate['pair_total']} vertical pairs.")
    print(f"{aggregate['pair_types']} total pair types, including "
          f"{aggregate['pair_types'] - aggregate['mixed_pair_types']} solid pairs; "
          f"{aggregate['retained_pair_types']} retained overall.")
    print(f"{aggregate['mixed_pair_types']} mixed pair types; {aggregate['retained_mixed_pair_types']} retained "
          f"at {args.min_count} occurrences ({aggregate['retained_mixed_share']:.2%} of mixed observations).")
    print(f"{aggregate['retained_edge_types']} retained neighbor links. Output: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
