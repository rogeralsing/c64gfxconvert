#!/usr/bin/env python3
"""Build monotonic eight-level C64 palette fades from the display palette."""

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
LEVELS = 8


def prepare(output):
    palette_file = HERE.parents[1] / "palettes" / "colodore.vpl"
    rgb = [tuple(int(value, 16) for value in line.split()[:3])
           for line in palette_file.read_text().splitlines()
           if line.strip() and not line.startswith("#")]
    if len(rgb) != 16 or rgb[0] != (0, 0, 0):
        raise ValueError("Expected sixteen C64 colors with black at index zero")
    luminance = [2126 * red + 7152 * green + 722 * blue for red, green, blue in rgb]
    paths = []
    for target in range(16):
        previous = {0: (0, (0,))}
        for level in range(1, LEVELS):
            candidates = (target,) if level == LEVELS - 1 else range(16)
            following = {}
            for color in candidates:
                if luminance[color] > luminance[target]:
                    continue
                error = sum(((LEVELS - 1) * actual - level * wanted) ** 2
                            for actual, wanted in zip(rgb[color], rgb[target]))
                predecessors = [(cost + error, path + (color,))
                                for old, (cost, path) in previous.items()
                                if luminance[old] <= luminance[color]]
                if predecessors:
                    following[color] = min(predecessors)
            previous = following
        paths.append(previous[target][1])
    maps = [[paths[color][level] for color in range(16)] for level in range(LEVELS)]
    packed = bytes((colors[value >> 4] << 4) | colors[value & 15]
                   for colors in maps for value in range(256))
    sprites = bytes(color for colors in maps for color in colors)
    assert len(packed) == LEVELS * 256 and len(sprites) == LEVELS * 16
    assert packed[:256] == bytes(256) and packed[-256:] == bytes(range(256))
    for color, path in enumerate(paths):
        assert path[0] == 0 and path[-1] == color
        assert all(luminance[first] <= luminance[second] for first, second in zip(path, path[1:]))
    output.mkdir(parents=True, exist_ok=True)
    (output / "scene-fade.bin").write_bytes(packed)
    (output / "scene-fade-sprites.bin").write_bytes(sprites)
    metadata = {"levels": LEVELS, "tiles_per_tick": 50,
                "palette_file": "palettes/colodore.vpl", "rgb": rgb,
                "luminance_weights": [2126, 7152, 722], "luminance": luminance,
                "color_paths": paths, "color_maps": maps,
                "method": "minimum RGB error against level/7 intensity, nondecreasing palette luminance"}
    (output / "scene-fade.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"fade_levels": LEVELS, "packed_bytes": len(packed),
                      "sprite_bytes": len(sprites), "tiles_per_tick": 50}))
    return metadata


if __name__ == "__main__":
    prepare(HERE / "build")
