#!/usr/bin/env python3
"""Normalize the supplied C64 export and add independent illusion flanks."""

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
WIDTH, HEIGHT = 160, 200
PALETTE = [
    "000000", "ffffff", "813338", "75cec8", "8e3c97", "56ac4d",
    "2e2c9b", "edf171", "8e5029", "553800", "c46c71", "4a4a4a",
    "7b7b7b", "a9ff9f", "706deb", "b2b2b2",
]
RGB = [tuple(bytes.fromhex(color)) for color in PALETTE]


def decode_source(archive):
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        font = source.read(manifest["files"]["charset"])
        screen = source.read(manifest["files"]["screen"])
        colors = source.read(manifest["files"]["colorRam"])
    if (len(font), len(screen), len(colors)) != (2048, 1000, 1000):
        raise ValueError("Expected a 2048-byte font and two 1000-byte maps")
    hardware = manifest["hardware"]
    background = hardware["backgroundColorRegister"]
    shared = hardware["sharedMulticolorRegisters"]
    pixels = []
    for y in range(HEIGHT):
        row = []
        for x in range(WIDTH * 2):
            cell = (y // 8) * 40 + x // 8
            byte = font[screen[cell] * 8 + y % 8]
            color = colors[cell]
            if color & 8:
                pair = (byte >> (6 - 2 * ((x % 8) // 2))) & 3
                value = [background, *shared, color & 7][pair]
            else:
                value = (color & 7) if byte & (128 >> (x % 8)) else background
            row.append(value)
        pixels.append(row)
    # Classify resolved colors, not raw bit pairs: some %11 pixels are black.
    mask = [
        [int(row[2 * x] != background or row[2 * x + 1] != background)
         for x in range(WIDTH)]
        for row in pixels
    ]
    widened = sum(
        (row[2 * x] != background) != (row[2 * x + 1] != background)
        for row in pixels for x in range(WIDTH)
    )
    return mask, pixels, widened


def add_borders(core, dx, dy, reverse=False):
    """Retain the core; put separate one-pixel strips on opposite sides."""
    leading, trailing = set(), set()
    occupied = {(x, y) for y, row in enumerate(core) for x, value in enumerate(row) if value}
    for x, y in occupied:
        for target, sign in ((leading, -1), (trailing, 1)):
            px, py = x + sign * dx, y + sign * dy
            if 0 <= px < WIDTH and 0 <= py < HEIGHT and (px, py) not in occupied:
                target.add((px, py))
    ambiguous = leading & trailing
    leading -= ambiguous
    trailing -= ambiguous
    result = [row[:] for row in core]
    for points, value in ((leading, 3 if reverse else 2), (trailing, 2 if reverse else 3)):
        for x, y in points:
            result[y][x] = value
    assert all(result[y][x] == 1 for x, y in occupied)
    return result, len(leading), len(trailing), len(ambiguous)


def place_pair(image):
    """Put two copies on screen; exchange only border polarity in the second."""
    result = [[0] * WIDTH for _ in range(HEIGHT)]
    for y, row in enumerate(image):
        for x, value in enumerate(row):
            if not value:
                continue
            for ox, swap in ((4, False), (88, True)):
                px, py = x + ox, y + 24
                if not (0 <= px < WIDTH and 0 <= py < HEIGHT):
                    raise ValueError("Cube does not fit the preview screen")
                result[py][px] = (5 - value) if swap and value in (2, 3) else value
    return result


def pack(image):
    glyphs = [bytes(8)]
    codes = {glyphs[0]: 0}
    screen = bytearray()
    for cy in range(25):
        for cx in range(40):
            glyph = bytes(
                sum(image[cy * 8 + y][cx * 4 + x] << (6 - 2 * x) for x in range(4))
                for y in range(8)
            )
            if glyph not in codes:
                codes[glyph] = len(glyphs)
                glyphs.append(glyph)
            screen.append(codes[glyph])
    if len(glyphs) > 256:
        raise ValueError(f"{len(glyphs)} glyphs exceed one charset")
    font = b"".join(glyphs).ljust(2048, b"\0")
    # Round-trip the hardware bit pairs, including cell boundaries.
    for y, row in enumerate(image):
        for x, value in enumerate(row):
            cell = (y // 8) * 40 + x // 4
            byte = font[screen[cell] * 8 + y % 8]
            assert ((byte >> (6 - 2 * (x % 4))) & 3) == value
    return font, bytes(screen), bytes([8] * 1000), len(glyphs)


def render(image, values=(12, 15, 1, 0)):
    output = Image.new("RGB", (320, 200))
    for y, row in enumerate(image):
        for x, value in enumerate(row):
            color = RGB[values[value]]
            output.putpixel((x * 2, y), color)
            output.putpixel((x * 2 + 1, y), color)
    return output


def write_assets(name, image, background):
    folder = BUILD / name
    folder.mkdir(parents=True, exist_ok=True)
    font, screen, colors, count = pack(image)
    for filename, data in (("charset.bin", font), ("screen.bin", screen), ("color-ram.bin", colors)):
        (folder / filename).write_bytes(data)
    manifest = {
        "format": "c64-multicolor-charset", "version": 1,
        "files": {"charset": "charset.bin", "screen": "screen.bin", "colorRam": "color-ram.bin"},
        "characterCount": count, "unrestrictedCharacterCount": count,
        "approximatedCellCount": 0, "hiresCellCount": 0, "multicolorCellCount": 1000,
        "layout": {"columns": 40, "rows": 25, "cellWidth": 8, "cellHeight": 8, "bytesPerGlyph": 8,
                   "charsetByteLength": 2048, "screenByteLength": 1000,
                   "colorRamByteLength": 1000, "loadAddressesIncluded": False},
        "image": {"width": 320, "height": 200, "pixelAspectRatio": [1, 1]},
        "hardware": {"bitmapMode": False, "extendedColorMode": False,
                     "multicolorMode": True, "backgroundColorRegister": background,
                     "sharedMulticolorRegisters": [1 if name == "clean" else 15, 1],
                     "colorRamModeBit": 8, "foregroundColorMask": 7,
                     "hiresCodes": ["background", "foreground"],
                     "multicolorCodes": ["background", "shared-1", "shared-2", "foreground"],
                     "programIncluded": False},
        "pixelRoles": {"00": "background", "01": "normalized cube core",
                       "10": "leading flank", "11": "trailing flank"},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if name == "demo":
        tail_cells = [cell for cell, code in enumerate(screen)
                      if any(byte & (byte >> 1) & 0x55 for byte in font[code * 8:code * 8 + 8])]
        (folder / "tail-stores.asm").write_text(
            "// Only cells with %11 pixels need the changing trailing color.\n"
            + "".join(f"    sta ${0xd800 + cell:04x}\n" for cell in tail_cells)
        )
    render(image, (background, 1 if name == "clean" else 15, 1, 0)).resize(
        (960, 600), Image.Resampling.NEAREST).save(folder / "preview.png")
    # Match the supplied archive layout, with the manifest at the archive root.
    with zipfile.ZipFile(BUILD / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in ("charset.bin", "screen.bin", "color-ram.bin", "manifest.json"):
            archive.write(folder / filename, filename)
    return count


def write_preview(clean, vertical, horizontal):
    images = {name: base64.b64encode(bytes(v for row in image for v in row)).decode()
              for name, image in (("clean", place_pair(clean)), ("vertical", place_pair(vertical)),
                                  ("horizontal", place_pair(horizontal)))}
    html = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>C64 cube font and illusion borders</title>
<style>body{margin:32px auto;max-width:1000px;padding:0 20px;background:#181a1d;color:#eee;font:16px system-ui}canvas{width:100%;image-rendering:pixelated;background:#7b7b7b}button,select,input{font:inherit;margin:8px 12px 8px 0}p{line-height:1.5}label{white-space:nowrap}</style>
<h1>C64 cube font and illusion borders</h1>
<p>The supplied cube, normalized to one foreground. Border variants retain the core and add independent one-pixel flanks. Both cubes share one timer; the right cube exchanges the flank roles.</p>
<canvas id="screen" width="320" height="200"></canvas>
<div><select id="shape"><option value="clean">Clean font</option><option value="vertical" selected>Vertical flanks</option><option value="horizontal">Horizontal flanks</option></select>
<select id="mode"><option value="still">Freeze: inspect borders</option><option value="single">Old bouncing ramp (comparison)</option><option value="dual">Two phase-shifted cycles</option><option value="wave" selected>Forward looping contrast wave</option></select>
<button id="play">Play</button><button id="reverse">Reverse time</button></div>
<label>Stage <input id="phase" type="range" min="0" max="95" value="12"></label>
<label>Speed <input id="speed" type="range" min="0.25" max="3" step="0.25" value="1"></label>
<p><b>Codes:</b> 00 background ($D021); 01 core ($D022); 10 leading flank ($D023); 11 trailing flank (Color RAM). Each multicolor pixel is two screen pixels wide.</p>
<p>The default cycle advances through six stages and wraps to the beginning. A single counter drives $D022, $D023, and the trailing border's Color RAM at different phases. Color RAM switches between 8 and 9, keeping multicolor enabled.</p>
<p>The old bouncing ramp is retained for comparison. It reverses its brightness progression halfway through. These timings are not a measured reconstruction of the original video. Use the frozen view to inspect the fixed geometry.</p>
<script>
const encoded=IMAGES, palette=PALETTE;
const masks=Object.fromEntries(Object.entries(encoded).map(([k,v])=>[k,Uint8Array.from(atob(v),c=>c.charCodeAt(0))]));
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),shape=document.querySelector('#shape'),mode=document.querySelector('#mode'),phase=document.querySelector('#phase'),speed=document.querySelector('#speed');
let running=false,sign=1,last=0,t=12;
const ramp=[0,11,12,15,1,15,12,11];
const waves=[[1,0,0],[1,1,0],[0,1,0],[0,1,1],[0,0,1],[1,0,1]];
function draw(){let p=Math.floor(t)%96,colors=[12,15,1,0];
 if(shape.value==='clean')colors=[0,1,1,0];
 else if(mode.value==='single')colors[1]=ramp[Math.floor(p/12)];
 else if(mode.value==='dual'){colors[1]=ramp[Math.floor(p/12)];colors[2]=ramp[(Math.floor(p/12)+2)%8];}
 else if(mode.value==='wave'){let [tail,core,lead]=waves[Math.floor(p/16)];colors=[12,core,lead,tail];}
 let data=ctx.createImageData(320,200),mask=masks[shape.value];
 for(let i=0;i<mask.length;i++){let rgb=palette[colors[mask[i]]];for(let d=0;d<2;d++){let j=(i*2+d)*4;data.data[j]=rgb[0];data.data[j+1]=rgb[1];data.data[j+2]=rgb[2];data.data[j+3]=255;}}
 ctx.putImageData(data,0,0);}
document.querySelector('#play').onclick=e=>{running=!running;e.target.textContent=running?'Pause':'Play';};
document.querySelector('#reverse').onclick=()=>{sign=-sign;};
for(let node of [shape,mode])node.onchange=draw;
phase.oninput=()=>{t=Number(phase.value);draw();};
function tick(now){if(running&&last){t=(t+sign*Math.min(now-last,100)*0.2*Number(speed.value)+96)%96;phase.value=Math.floor(t);draw();}last=now;requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script></html>"""
    html = html.replace("IMAGES", json.dumps(images)).replace("PALETTE", json.dumps(RGB))
    (BUILD / "preview.html").write_text(html)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "source.zip")
    parser.add_argument("--assets-only", action="store_true")
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    core, original, widened = decode_source(args.source)
    vertical, *vertical_counts = add_borders(core, 0, 1)
    horizontal, *horizontal_counts = add_borders(core, 1, 0)
    counts = {
        "clean": write_assets("clean", core, 0),
        "bordered-vertical": write_assets("bordered-vertical", vertical, 12),
        "bordered-horizontal": write_assets("bordered-horizontal", horizontal, 12),
        "demo": write_assets("demo", place_pair(vertical), 12),
    }
    source_image = Image.new("RGB", (320, 200))
    source_image.putdata([RGB[value] for row in original for value in row])
    source_image.resize((960, 600), Image.Resampling.NEAREST).save(BUILD / "source.png")
    # Side-by-side views use the same crop and scale, so changes remain visible.
    comparison = Image.new("RGB", (900, 336), "#181a1d")
    draw = ImageDraw.Draw(comparison)
    for i, (label, im) in enumerate((("Source export", source_image),
                                   ("Clean: one foreground", render(core, (0, 1, 1, 0))),
                                   ("Copy: separate border strips", render(vertical)))):
        draw.text((i * 300 + 8, 10), label, fill="white")
        crop = im.crop((0, 0, 144, 152)).resize((288, 304), Image.Resampling.NEAREST)
        comparison.paste(crop, (i * 300 + 6, 28))
    comparison.save(BUILD / "comparison.png")
    write_preview(core, vertical, horizontal)
    report = {
        "sourceSha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "characters": counts,
        "foregroundMulticolorPixels": sum(map(sum, core)),
        "physicalPixelsAddedByMulticolorAlignment": widened,
        "verticalBorders": dict(zip(("leading", "trailing", "ambiguousRemoved"), vertical_counts)),
        "horizontalBorders": dict(zip(("leading", "trailing", "ambiguousRemoved"), horizontal_counts)),
        "checks": ["all source visible foreground retained after pair alignment",
                   "all normalized foreground uses bit pair 01",
                   "border generation leaves core unchanged",
                   "charset/screen bit-pair round trips passed",
                   "all charsets fit 256 glyphs; all Color RAM bytes equal 8"],
    }
    if not args.assets_only:
        assembler = shutil.which("kickass") or "/Users/rogerjohansson/.local/bin/kickass"
        subprocess.run([assembler, "player.asm", "-odir", "build", "-o", "build/cube-illusion.prg",
                        "-symbolfile"], cwd=ROOT, check=True)
    (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    with zipfile.ZipFile(BUILD / "cube-fonts.zip", "w", zipfile.ZIP_DEFLATED) as output:
        for name in counts:
            for file in sorted((BUILD / name).iterdir()):
                output.write(file, file.relative_to(BUILD))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
