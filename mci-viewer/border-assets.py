"""Read the converter's native, two-field side-sprite export without refitting it."""

import hashlib
import json
import zipfile


def read_border_assets(path, background):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        sprites = archive.read("sprites.bin")
    invalid = lambda: ValueError("Expected a two-field 368x200 side-only border-sprite export.")
    color = lambda value: type(value) is int and 0 <= value <= 15
    if manifest.get("format") != "c64-border-sprites" or manifest.get("version") != 1 or manifest.get("interlaced") is not True:
        raise invalid()
    image = manifest.get("image", {})
    settings = manifest.get("settings", {})
    vertical, sides = settings.get("vertical", {}), settings.get("sides", {})
    shared = settings.get("multicolorIndices")
    if image.get("width") != 368 or image.get("height") != 200 or image.get("core") != {"x": 24, "y": 0, "width": 320, "height": 200} or vertical.get("enabled") is not False or sides.get("enabled") is not True:
        raise invalid()
    if sides.get("mode") not in ("hires", "multicolor") or not color(sides.get("colorIndex")) or not isinstance(shared, list) or len(shared) != 2 or not all(color(value) for value in shared):
        raise invalid()
    hardware = manifest.get("hardware", {})
    if hardware.get("backgroundColorRegister") != background or hardware.get("sharedMulticolorRegisters") != shared:
        raise ValueError("Border-sprite colors do not match the source MCI/background settings.")
    if background != 0:
        raise ValueError("The side-only player currently requires a black background for blank upper/lower borders.")
    fields = manifest.get("fields")
    records = manifest.get("sprites")
    if not isinstance(fields, list) or len(fields) != 2 or not isinstance(records, list) or len(records) != 40 or len(sprites) != 2560:
        raise invalid()
    for phase, field in enumerate(fields):
        expected = {"phase": phase, "offsetX": phase, "spriteOffset": phase * 20,
                    "spriteCount": 20, "byteOffset": phase * 1280, "byteLength": 1280}
        if field != expected:
            raise invalid()
        for local in range(20):
            index = phase * 20 + local
            record = records[index]
            band = local % 10
            right = local >= 10
            last = band == 9
            x = (344 if right else 0) + phase
            y = 179 if last else 21 * band
            expected = {"index": index, "field": phase, "group": "right" if right else "left",
                        "band": band, "hardwareSlot": (4 if right else 3) + (2 if last else 0),
                        "x": x, "y": y, "vicX": x, "vicY": y + 50,
                        "mode": sides["mode"], "multicolor": sides["mode"] == "multicolor",
                        "colorIndex": sides["colorIndex"], "xExpanded": False, "yExpanded": False,
                        "displayWidth": 24, "displayHeight": 21, "rowHeights": [1] * 21,
                        "clip": {"x": x, "y": 189 if last else 0, "width": 24, "height": 11 if last else 200},
                        "byteOffset": index * 64, "byteLength": 64}
            if any(record.get(key) != value for key, value in expected.items()):
                raise invalid()
            data = sprites[index * 64:(index + 1) * 64]
            if data[63] or last and any(data[:30]):
                raise ValueError("Native sprite padding or final-strip transparent rows are invalid.")
    constants = "\n".join((
        f".const BORDER_SHARED_1 = {shared[0]}",
        f".const BORDER_SHARED_2 = {shared[1]}",
        f".const BORDER_SPRITE_COLOR = {sides['colorIndex']}",
        f".const BORDER_MULTICOLOR_MASK = {0x78 if sides['mode'] == 'multicolor' else 0}",
    )) + "\n"
    return {"manifest": manifest, "data": sprites, "constants": constants,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sprite_sha256": hashlib.sha256(sprites).hexdigest()}
