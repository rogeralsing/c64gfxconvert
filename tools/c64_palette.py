"""Read VICE palettes and snap RGB channels without dithering or alpha changes."""

from pathlib import Path

import numpy as np
from PIL import Image


def load_palette(path):
    """Load exactly sixteen distinct 8-bit RGB colors from a VICE .vpl file."""
    colors = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        columns = line.split("#", 1)[0].split()
        if not columns:
            continue
        if len(columns) not in (3, 4):
            raise ValueError(f"Palette line {line_number}: expected three or four hexadecimal columns.")
        try:
            values = [int(column, 16) for column in columns]
        except ValueError as error:
            raise ValueError(f"Palette line {line_number}: invalid hexadecimal value.") from error
        if any(value < 0 or value > 255 for value in values):
            raise ValueError(f"Palette line {line_number}: values must fit in an 8-bit channel.")
        colors.append(tuple(values[:3]))
    if len(colors) != 16 or len(set(colors)) != 16:
        raise ValueError("Palette must contain exactly 16 distinct RGB colors.")
    return np.asarray(colors, dtype=np.uint8)


def snap_palette(image, palette):
    """Choose nearest Euclidean RGB colors, retaining image size and alpha."""
    source = np.asarray(image.convert("RGB"), dtype=np.int32)
    rgb = source.reshape(-1, 3)
    colors = np.asarray(palette, dtype=np.int32)
    differences = rgb[:, None, :] - colors[None, :, :]
    squared_distances = np.sum(differences * differences, axis=2)
    indices = squared_distances.argmin(axis=1)
    nearest = colors[indices].astype(np.uint8).reshape(source.shape)
    if "A" in image.getbands():
        nearest = np.dstack((nearest, np.asarray(image.getchannel("A"))))
    output = Image.fromarray(nearest)

    distances = np.sqrt(squared_distances[np.arange(len(rgb)), indices])
    usage = np.bincount(indices, minlength=16)
    record = {
        "source_unique_rgb": int(len(np.unique(rgb, axis=0))),
        "output_unique_rgb": int(np.count_nonzero(usage)),
        "palette_usage": usage.tolist(),
        "mean_rgb_distance": float(distances.mean()),
        "p95_rgb_distance": float(np.percentile(distances, 95)),
        "max_rgb_distance": float(distances.max()),
    }
    return output, record
