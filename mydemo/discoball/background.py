#!/usr/bin/env python3
"""Prepare Koala or True Paint MCI fields and private disco color cells."""

import hashlib
import json
from pathlib import Path

from prepare_disco import prepare as prepare_disco

def prepare(output):
    calibration = json.loads((Path(__file__).resolve().parent / "assets" / "scene-circle-repair.json").read_text())
    asset = calibration.get("source_asset", "assets/scene.koa")
    source = (Path(__file__).resolve().parent / asset).read_bytes()
    if calibration["source_sha256"] != hashlib.sha256(source).hexdigest():
        raise ValueError("The circle origin manifest does not match the supplied scene")
    interlaced = asset.endswith(".mci")
    if interlaced:
        if len(source) != 19434 or source[:2] != bytes((0, 0x9c)):
            raise ValueError("Expected an uncompressed True Paint MCI image")
        bitmap, bitmap_b = source[1026:9026], source[9218:17218]
        screen, screen_b = source[2:1002], source[17410:18410]
        colors, background = bytes(v & 15 for v in source[18434:19434]), source[1002] & 15
    else:
        if len(source) != 10003:
            raise ValueError("Expected a 10003-byte Koala multicolor image")
        bitmap = bitmap_b = source[2:8002]
        screen = screen_b = source[8002:9002]
        colors, background = bytes(v & 15 for v in source[9002:10002]), source[10002] & 15
    center_x, center_y = calibration["center"]
    bitmap, bitmap_b, screen, screen_b, colors, disco, disco_asm = prepare_disco(
        bitmap, bitmap_b, screen, screen_b, colors, background, (center_x, center_y))
    output.mkdir(parents=True, exist_ok=True)
    (output / "ball-bitmap.bin").write_bytes(bitmap)
    (output / "ball-bitmap-b.bin").write_bytes(bitmap_b)
    (output / "ball-screen-b.bin").write_bytes(screen_b)
    (output / "ball-screen.bin").write_bytes(screen)
    (output / "ball-colors.bin").write_bytes(colors)
    (output / "disco.asm").write_text(disco_asm)
    metadata = {"source": asset, "source_sha256": hashlib.sha256(source).hexdigest(),
                "center": [center_x, center_y], "background": background,
                "bitmap_passthrough": False,
                "source_render_preserved": not any(disco["edge_recolored_multicolor_pixels"]),
                "generated_dithering": False, "disco": disco,
                "format": "truepaint_mci" if interlaced else "koala",
                "phase_count": 2 if interlaced else 1, "horizontal_phase_shift": int(interlaced)}
    (output / "scene.json").write_text(json.dumps(metadata, indent=2)+"\n")
    constants = {"CENTER_X": center_x, "CENTER_Y": center_y,
                 "BACKGROUND": background, "SCROLL_XOR": int(interlaced),
                 "X_BIAS": (center_x-104) & 255, "Y_BIAS": (center_y-78) & 255,
                 "X_OFFSET": center_x-128, "Y_OFFSET": center_y-128}
    (output / "scene.asm").write_text("// Graphics origin measured from the supplied white circle.\n"+
                                    "".join(f".const SCENE_{key} = {value}\n" for key, value in constants.items()))
    print(json.dumps(metadata))


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parent / "build")
