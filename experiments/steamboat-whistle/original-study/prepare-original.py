#!/usr/bin/env python3
"""Extract forward original movie frames and matching, unretimed audio.

This is source preparation only. It does not crop, resize, grade, threshold,
rematch characters, change source order, or alter the soundtrack's tempo.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave


SOURCE_URL = "https://upload.wikimedia.org/wikipedia/commons/5/5f/Steamboat_Willie_%281928%29_by_Walt_Disney.webm"


def command(arguments: list[str], *, binary: bool = False):
    result = subprocess.run(["rtk", "proxy", *arguments], capture_output=True,
                            text=not binary, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr if not binary else result.stderr.decode())
    return result


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def prepare(source: Path, output: Path, start: float, duration: float, fps: int) -> dict:
    source, output = source.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_sha = digest(source)
    probe = json.loads(command(["ffprobe", "-v", "error", "-show_format",
                                "-show_streams", "-of", "json", str(source)]).stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    width, height = video["width"], video["height"]
    if audio["channels"] != 1 or int(audio["sample_rate"]) != 48000:
        raise ValueError("This source proof requires original mono 48-kHz audio")
    time_base = Fraction(video["time_base"])
    frame_probe = json.loads(command([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals",
        f"0%{start + duration + 1}", "-show_frames", "-show_entries",
        "frame=best_effort_timestamp,best_effort_timestamp_time", "-of", "json", str(source)]).stdout)
    source_frames = [(int(frame["best_effort_timestamp"]),
                      float(frame["best_effort_timestamp_time"]))
                     for frame in frame_probe["frames"]]
    count = round(duration * fps)
    if count <= 0 or abs(count / fps - duration) > 1e-9:
        raise ValueError("Duration must contain a whole number of output frames")
    targets = [start + index / fps for index in range(count)]
    selected = [min(source_frames, key=lambda item: abs(item[1] - target))
                for target in targets]
    ticks = [item[0] for item in selected]
    if any(b <= a for a, b in zip(ticks, ticks[1:])):
        raise ValueError("Native source selection must advance uniquely and monotonically")
    native_period = 1 / float(Fraction(video["avg_frame_rate"]))
    errors = [selected[index][1] - target for index, target in enumerate(targets)]
    if max(map(abs, errors)) > native_period / 2 + .001:
        raise ValueError("Input does not cover all requested source times")
    selection = "+".join(f"eq(pts,{tick})" for tick in ticks)
    rgb = output / "original.rgb"
    rgb_pending = output / "original.rgb.part"
    extraction = ["ffmpeg", "-hide_banner", "-v", "info", "-copyts", "-ss",
                  str(max(0, start - 1)), "-i", str(source), "-map", "0:v:0",
                  "-an", "-vf", f"select='{selection}',showinfo,format=rgb24",
                  "-frames:v", str(count), "-fps_mode", "passthrough", "-pix_fmt",
                  "rgb24", "-f", "rawvideo", "-y", str(rgb_pending)]
    decoded = command(extraction)
    (output / "rgb-extraction.log").write_text(decoded.stderr)
    observed = [float(value) for value in re.findall(r"pts_time:([\d.]+)", decoded.stderr)]
    expected_pts = [item[1] for item in selected]
    if len(observed) != count or any(abs(a - b) > 1e-6 for a, b in zip(observed, expected_pts)):
        raise ValueError(f"Decoded source timestamps differ: {observed}")
    if rgb_pending.stat().st_size != width * height * 3 * count:
        raise ValueError("Incomplete native RGB frame output")
    rgb_pending.replace(rgb)
    wav = output / "original-audio.wav"
    audio_command = ["ffmpeg", "-v", "error", "-i", str(source),
                     "-af", f"atrim=start={start}:end={start + duration},asetpts=PTS-STARTPTS",
                     "-map", "0:a:0", "-vn", "-ac", "1",
                     "-ar", "48000", "-c:a", "pcm_s16le", "-y", str(wav)]
    command(audio_command)
    # Decode the original audio clock from its first source PTS, then select
    # the same absolute interval by sample index. Input seeking alone produced
    # a different PCM phase in this truncated WebM, so it is not authoritative.
    full_pcm = command(["ffmpeg", "-v", "error", "-i", str(source), "-t",
                        str(start + duration + 1), "-map", "0:a:0", "-vn", "-ac", "1",
                        "-ar", "48000", "-f", "s16le", "pipe:1"], binary=True).stdout
    audio_origin_samples = round(float(audio["start_time"]) * 48000)
    first_sample = round(start * 48000) - audio_origin_samples
    final_sample = round((start + duration) * 48000) - audio_origin_samples
    independent = full_pcm[first_sample * 2:final_sample * 2]
    with wave.open(str(wav), "rb") as stream:
        sample_count, sample_rate = stream.getnframes(), stream.getframerate()
        pcm = stream.readframes(sample_count)
    if sample_count != round(duration * 48000) or sample_rate != 48000 or pcm != independent:
        raise ValueError("Original audio sample count or independent full-timeline proof failed")
    lossless = output / "original-10fps.mkv"
    command(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
             f"{width}x{height}", "-r", str(fps), "-i", str(rgb), "-an", "-c:v",
             "ffv1", "-level", "3", "-pix_fmt", "bgr0", "-y", str(lossless)])
    roundtrip = command(["ffmpeg", "-v", "error", "-i", str(lossless), "-an", "-f",
                         "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], binary=True).stdout
    if hashlib.sha256(roundtrip).hexdigest() != digest(rgb):
        raise ValueError("Lossless RGB container did not retain every RGB source byte")
    if digest(source) != source_sha:
        raise ValueError("Source input changed during extraction")
    metadata = {
        "passed": True, "source": str(source), "sourceURL": SOURCE_URL,
        "sourceSha256": source_sha, "sourceBytes": source.stat().st_size,
        "sourceVideoCodec": video["codec_name"], "sourcePixelFormat": video["pix_fmt"],
        "sourceWidth": width, "sourceHeight": height,
        "sourceFPS": video["avg_frame_rate"], "sourceTimeBase": str(time_base),
        "sourceAudioCodec": audio["codec_name"], "sourceAudioStartSeconds": float(audio["start_time"]),
        "startSeconds": start, "durationSeconds": duration, "fps": fps, "frameCount": count,
        "frameSelection": "Nearest original decoded PTS to each start+i/fps; unique and forward only",
        "targetSourceTimes": targets, "selectedSourceTicks": ticks, "selectedSourcePTS": expected_pts,
        "sourceSamplingErrorsSeconds": errors, "maximumSourceSamplingErrorSeconds": max(map(abs, errors)),
        "rgbFile": str(rgb), "rgbFormat": "rgb24", "rgbBytes": rgb.stat().st_size,
        "rgbSha256": digest(rgb), "losslessVideoFile": str(lossless),
        "losslessVideoSha256": digest(lossless), "losslessRGBRoundtripPassed": True,
        "audioFile": str(wav), "audioSha256": digest(wav), "audioPCMsha256": hashlib.sha256(pcm).hexdigest(),
        "audioSamples": sample_count, "audioRate": sample_rate, "audioChannels": 1,
        "independentFullAudioTimelineProofPassed": True,
        "audioOriginSamplesAt48kHz": audio_origin_samples,
        "processing": "Original YUV decoded to full native RGB24 only. No grade, crop, resize, grayscale, threshold or font mapping. Audio is the same original interval, decoded to mono PCM16 at its native 48-kHz rate; no offset adjustment, tempo change, gate, fades or gain.",
        "rgbExtractionCommand": extraction, "audioExtractionCommand": audio_command,
    }
    (output / "source.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({key: metadata[key] for key in ("passed", "sourceWidth", "sourceHeight",
          "startSeconds", "durationSeconds", "fps", "frameCount", "maximumSourceSamplingErrorSeconds",
          "rgbFile", "rgbSha256", "audioFile", "audioSamples", "audioSha256")}, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] /
                        "work/original-calibration/source")
    parser.add_argument("--start", type=float, default=32)
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()
    if args.start < 0 or args.duration <= 0 or args.fps <= 0:
        parser.error("Start must be nonnegative; duration and FPS must be positive")
    prepare(args.input, args.output, args.start, args.duration, args.fps)


if __name__ == "__main__":
    main()
