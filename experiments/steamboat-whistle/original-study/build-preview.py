#!/usr/bin/env python3
"""Build an original-film calibration preview without changing approved assets.

The manifest contains a candidates array. Each candidate's name selects a
directory beside the manifest containing 320x200 uint8 binary.frames. Optional
label and description fields control the preview's wording.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
from pathlib import Path
import re
import subprocess
import wave

from PIL import Image


EXPERIMENT = Path(__file__).resolve().parents[1]
CALIBRATION = EXPERIMENT / "work/original-calibration"
LABELS = {"cleaner": "Renare", "balance": "Balans", "contours": "Mer konturer",
          "detail": "Mer detaljer", "outlines": "Tydliga konturer",
          "adaptive": "Kontrast per bildruta"}
DESCRIPTIONS = {
    "cleaner": "Renare bakgrund och tunnare linjer.",
    "balance": "Balans mellan rena ytor och tydliga konturer.",
    "contours": "Fler konturer och något kraftigare svärta.",
    "detail": "Fler mörka detaljer bevaras i originalets linjer.",
    "outlines": "Fasta nivåer och förstärkta linjer i originalupplösningen ger tydligare konturer.",
    "adaptive": "Kontrastnivåerna väljs separat för varje bildruta. En jämförelse med det fasta standardläget.",
}


def command(arguments: list[str], *, binary: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(["rtk", "proxy", *arguments], capture_output=True,
                            text=not binary, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode() if binary else result.stderr)
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_data(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def approved_still(folder: Path, frame: int) -> Image.Image:
    font = (folder / "font.bin").read_bytes()
    screens = (folder / "screen.frames").read_bytes()
    if len(font) != 2048 or len(screens) % 1000:
        raise ValueError("Invalid approved C64 font or screen data")
    screen = screens[frame * 1000:(frame + 1) * 1000]
    if len(screen) != 1000:
        raise ValueError("Approved reference frame is unavailable")
    pixels = bytearray([255]) * 64000
    for cell, char in enumerate(screen):
        x, y = (cell % 40) * 8, (cell // 40) * 8
        for row in range(8):
            bits = font[char * 8 + row]
            for column in range(8):
                if bits & (128 >> column):
                    pixels[(y + row) * 320 + x + column] = 0
    return Image.frombytes("L", (320, 200), bytes(pixels)).resize(
        (600, 400), Image.Resampling.NEAREST)


def build(manifest: Path, output: Path, approved: Path, source: Path,
          reference_frame: int, default: str) -> dict:
    manifest, output, approved, source = (path.resolve() for path in
                                         (manifest, output, approved, source))
    output.mkdir(parents=True, exist_ok=True)
    source_proof = json.loads((source / "source.json").read_text())
    audio = source / "original-audio.wav"
    if not source_proof.get("passed") or sha256(audio) != source_proof["audioSha256"]:
        raise ValueError("Original audio does not match the verified source proof")
    fps, count = source_proof["fps"], source_proof["frameCount"]
    duration = source_proof["durationSeconds"]
    start = source_proof["startSeconds"]
    with wave.open(str(audio), "rb") as stream:
        if (stream.getnframes(), stream.getframerate(), stream.getnchannels()) != (
                round(duration * 48000), 48000, 1):
            raise ValueError("Expected the complete original mono soundtrack interval")
    protected = {str(path): sha256(path) for path in
                 (approved / "font.bin", approved / "screen.frames", audio)}
    config = json.loads(manifest.read_text())
    presets = []
    for candidate in config["candidates"]:
        name = candidate["name"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise ValueError(f"Unsafe preset name: {name}")
        raw = manifest.parent / name / "binary.frames"
        data = raw.read_bytes()
        if len(data) != count * 320 * 200 or set(data) - {0, 255}:
            raise ValueError(f"Expected {count} complete binary frames: {raw}")
        expected_hash = candidate.get("hashes", {}).get("binary.frames")
        if expected_hash and sha256(raw) != expected_hash:
            raise ValueError(f"Preset hash does not match manifest: {raw}")
        video = output / f"original-{name}.mp4"
        command(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format",
                 "gray", "-video_size", "320x200", "-framerate", str(fps), "-i",
                 str(raw), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                 "-vf", "scale=600:400:flags=neighbor,setsar=1", "-frames:v",
                 str(count), "-t", str(duration), "-c:v", "libx264", "-preset",
                 "slow", "-crf", "1", "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
                 "-y", str(video)])
        probe = json.loads(command(["ffprobe", "-v", "error", "-count_frames",
                                     "-show_streams", "-show_format", "-of", "json",
                                     str(video)]).stdout)
        v = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        a = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
        if (v["width"], v["height"], int(v["nb_read_frames"]), v["r_frame_rate"]) != (
                600, 400, count, f"{fps}/1"):
            raise ValueError(f"Video dimensions, frame count or rate differ: {video}")
        if any(abs(float(item["duration"]) - duration) > .001 for item in
               (probe["format"], v, a)):
            raise ValueError(f"Video and audio must both last exactly {duration}s: {video}")
        expected = command(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format",
                            "gray", "-video_size", "320x200", "-framerate", str(fps), "-i",
                            str(raw), "-vf", "scale=600:400:flags=neighbor,setsar=1", "-an",
                            "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"], binary=True).stdout
        decoded = command(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0",
                           "-an", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"], binary=True).stdout
        if len(decoded) != count * 600 * 400 or bytes(x >= 128 for x in expected) != bytes(
                x >= 128 for x in decoded):
            raise ValueError(f"Preview compression changed a binary pixel's classification: {video}")
        poster = Image.frombytes("L", (320, 200), data[:64000]).resize(
            (600, 400), Image.Resampling.NEAREST)
        presets.append({"name": name, "label": candidate.get("label", LABELS.get(name, name)),
                        "description": candidate.get("description", DESCRIPTIONS.get(name, "")),
                        "file": video.name, "poster": image_data(poster),
                        "inputBinarySha256": sha256(raw),
                        "bytes": video.stat().st_size, "sha256": sha256(video),
                        "frameCount": count, "fps": fps, "durationSeconds": duration,
                        "videoProfile": v["profile"], "decodedBinaryClassificationMatches": True,
                        "audioDurationSeconds": float(a["duration"]),
                        "audioRate": int(a["sample_rate"]), "audioChannels": int(a["channels"])})
    names = [preset["name"] for preset in presets]
    if not presets or len(set(names)) != len(names) or default not in names:
        raise ValueError("Need unique presets including the selected default")
    selected = presets[names.index(default)]
    reference = image_data(approved_still(approved, reference_frame))
    options = "".join(f'<option value="{html.escape(p["name"])}"'
                      f'{" selected" if p["name"] == default else ""}>'
                      f'{html.escape(p["label"])}</option>' for p in presets)
    script_data = json.dumps(presets, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!doctype html>
<html lang="sv"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Musse · Originalfilm och stilreferens</title>
<link rel="icon" href="data:,">
<style>
:root{color-scheme:dark;font-family:"Segoe UI",system-ui,sans-serif;background:#121510;color:#e9ede0}
*{box-sizing:border-box}body{margin:0}main{max-width:1320px;margin:auto;padding:32px 24px 40px}
h1{font-size:clamp(25px,3vw,36px);font-weight:650;margin:0 0 10px}p{line-height:1.5;margin:0;color:#b8c0ad}
.lead{max-width:850px}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:30px 0 20px}
figure{margin:0;min-width:0}h2{font-size:18px;font-weight:650;margin:0 0 8px}.tag{font:13px ui-monospace,monospace;color:#ccec83;margin-bottom:14px}
.media{width:100%;aspect-ratio:3/2;background:white;border:1px solid #3c4433;display:block;image-rendering:pixelated}
.caption{font-size:14px;min-height:44px;margin-top:12px}.toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:14px}
select,button{font:inherit;border:1px solid #525c46;border-radius:5px;min-height:40px;padding:7px 12px}select{background:#1b2116;color:#e9ede0}
button{background:#ccec83;color:#18200c;font-weight:600;cursor:pointer}button:hover{background:#dbf5a3}button:focus-visible,select:focus-visible{outline:2px solid #d8f395;outline-offset:3px}
.process{border-top:1px solid #343d2b;padding-top:18px;font-size:14px}.sound-status{font-size:13px;color:#b8c0ad}
@media(max-width:780px){main{padding:24px 16px}.comparison{grid-template-columns:1fr;gap:28px}.caption{min-height:0}}
</style>
<main>
<h1>Musse från originalfilmen</h1>
<p class="lead">Målet är GIF-versionens rena svartvita uttryck, med rörelser och ljud från originalfilmen.</p>
<div class="comparison">
<figure><h2>Godkänd stilreferens</h2><div class="tag">GIF-versionens teckenbild · ruta REFERENCE_FRAME</div>
<img class="media" src="REFERENCE_IMAGE" alt="Godkänd svartvit Musse rekonstruerad ur C64-font och skärmdata">
<p class="caption">En stillbild som visar önskad stil. Den är inte en synkroniserad GIF.</p></figure>
<figure><h2>Originalets animation</h2><div class="tag">Original START–END s · FPS fps · 6 sekunder</div>
<video id="movie" class="media" src="SELECTED_FILE" poster="SELECTED_POSTER" controls loop autoplay muted playsinline></video>
<p id="description" class="caption">SELECTED_DESCRIPTION</p>
<div class="toolbar"><label for="preset">Kontrast</label><select id="preset">PRESET_OPTIONS</select><button id="sound" type="button">Spela med ljud</button></div>
<p class="sound-status">Originalets vissling. Ingen ändrad hastighet eller klippning mitt i sekvensen.</p></figure>
</div>
<p class="process">Kontrasten korrigeras i originalets 1296 × 1080 pixlar, före beskärning och nedskalning. Standardläget använder fasta nivåer och förstärkta linjer. Kontrast per bildruta finns som jämförelse. Högerbilden är bitmappen före teckenmappning; delar av originalets skepp kan finnas kvar i bakgrunden.</p>
</main>
<script>
const presets=PRESET_DATA;
const movie=document.getElementById('movie');
document.getElementById('preset').addEventListener('change',event=>{
  const preset=presets.find(item=>item.name===event.target.value);
  const time=movie.currentTime; const paused=movie.paused;
  movie.src=preset.file; movie.poster=preset.poster;
  document.getElementById('description').textContent=preset.description;
  movie.addEventListener('loadedmetadata',()=>{movie.currentTime=Math.min(time,movie.duration-.01);if(!paused)movie.play().catch(()=>{});},{once:true});
  movie.load();
});
document.getElementById('sound').addEventListener('click',()=>{movie.muted=false;movie.play().catch(()=>{});});
</script></html>
"""
    substitutions = {"REFERENCE_FRAME": str(reference_frame), "REFERENCE_IMAGE": reference,
                     "START": f"{start:g}", "END": f"{start + duration:g}", "FPS": str(fps),
                     "SELECTED_FILE": html.escape(selected["file"]), "SELECTED_POSTER": selected["poster"],
                     "SELECTED_DESCRIPTION": html.escape(selected["description"]),
                     "PRESET_OPTIONS": options, "PRESET_DATA": script_data}
    for key, value in substitutions.items():
        page = page.replace(key, value)
    (output / "index.html").write_text(page)
    if any(sha256(Path(path)) != digest for path, digest in protected.items()):
        raise ValueError("Approved reference assets or original audio changed during build")
    result = {"passed": True, "page": str(output / "index.html"), "defaultPreset": default,
              "presets": [{k: v for k, v in preset.items() if k != "poster"} for preset in presets],
              "sourceStartSeconds": start, "sourceDurationSeconds": duration,
              "manifestSha256": sha256(manifest),
              "audioSourceSha256": protected[str(audio)],
              "audioProcessing": "AAC delivery encoding only; no trim, gain, gate, fade, resampling or retiming",
              "protectedInputsUnchanged": True, "protectedInputSha256": protected}
    (output / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=CALIBRATION / "contrast/final-presets.json")
    parser.add_argument("--output", type=Path, default=CALIBRATION / "preview")
    parser.add_argument("--approved", type=Path, default=EXPERIMENT / "assets/approved")
    parser.add_argument("--source", type=Path, default=CALIBRATION / "source")
    parser.add_argument("--reference-frame", type=int, default=28)
    parser.add_argument("--default", default="balance")
    args = parser.parse_args()
    build(args.manifest, args.output, args.approved, args.source, args.reference_frame, args.default)


if __name__ == "__main__":
    main()
