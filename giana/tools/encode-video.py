#!/usr/bin/env python3
"""Mux native captured PAL fields and same-instance audio, ending at MCI + 30 s."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def probe(path, *arguments):
    command = ["ffprobe", "-v", "error", *arguments, "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("capture", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
capture = args.capture.resolve()
output = (args.output or capture.parent / "giana-complete-mci-30s.mp4").resolve()
receipt = json.loads((capture / "receipt.json").read_text())
assert receipt["passed"] and receipt["complete_demo"]
assert len(receipt["mci_fields"]) == 1504
frames = receipt["video_frames"]
onset = receipt["mci_onset_image_index"]
assert frames == onset + 1504
assert {field["completed_phase"] for field in receipt["mci_fields"]} == {0, 1}
assert len(set(receipt["mci_phase_rgb_sha256"].values())) == 2
native_proof = ROOT / "giana/assets"
for phase in (0, 1):
    with Image.open(native_proof / f"mci-phase-{phase}.png") as image:
        expected = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
    assert receipt["mci_phase_rgb_sha256"][str(phase)] == expected, ("MCI differs from native proof", phase)
end_ticks = onset * 273 + 30 * 13684
assert end_ticks - (frames - 1) * 273 == 201
audio_count = round(end_ticks * 44100 / 13684)
cropped_audio = capture / "delivery-audio.wav"
with wave.open(str(capture / "native-interval-audio.wav"), "rb") as source:
    assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (44100, 1, 2)
    pcm = source.readframes(audio_count)
assert len(pcm) == audio_count * 2
with wave.open(str(cropped_audio), "wb") as destination:
    destination.setnchannels(1)
    destination.setsampwidth(2)
    destination.setframerate(44100)
    destination.writeframes(pcm)

# PTS stays at exact native PAL cadence. Only the final sample duration changes;
# no field is duplicated, blended, omitted, or played faster/slower.
packet_duration = f"setts=duration=if(eq(N\\,{frames - 1})\\,201\\,273)"
command = [
    "ffmpeg", "-hide_banner", "-y", "-framerate", "13684/273", "-start_number", "0",
    "-i", str(capture / "frame-%05d.png"), "-i", str(cropped_audio),
    "-map", "0:v:0", "-map", "1:a:0",
    "-vf", "crop=320:200:32:35,scale=1280:800:flags=neighbor",
    "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-threads:v", "4",
    "-pix_fmt", "yuv420p", "-bf:v", "0", "-enc_time_base:v", "1/13684",
    "-fps_mode:v", "passthrough", "-video_track_timescale", "13684",
    "-movie_timescale", "13684", "-bsf:v", packet_duration,
    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "1",
    "-movflags", "+faststart", "-metadata", "title=Giana demo — complete, MCI 30 seconds",
    str(output),
]
with (capture / "encode.log").open("w") as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)

streams = probe(output, "-show_streams", "-show_format")
video = next(stream for stream in streams["streams"] if stream["codec_type"] == "video")
audio = next(stream for stream in streams["streams"] if stream["codec_type"] == "audio")
assert (video["codec_name"], video["width"], video["height"]) == ("h264", 1280, 800)
assert video["nb_frames"] == str(frames)
assert video["time_base"] == "1/13684"
assert int(video["duration_ts"]) == end_ticks
assert audio["codec_name"] == "aac" and audio["sample_rate"] == "44100"
assert int(audio["duration_ts"]) == audio_count
packets = probe(output, "-select_streams", "v:0", "-show_packets",
                "-show_entries", "packet=pts,dts,duration")["packets"]
assert len(packets) == frames
for index, packet in enumerate(packets):
    assert packet["pts"] == packet["dts"] == index * 273, (index, packet)
    assert packet["duration"] == (201 if index == frames - 1 else 273), (index, packet)
assert end_ticks - packets[onset]["pts"] == 30 * 13684
subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"], check=True)

poster = output.with_suffix(".png")
with Image.open(capture / "frame-00000.png") as image:
    image.convert("RGB").crop((32, 35, 352, 235)).resize(
        (1280, 800), Image.Resampling.NEAREST).save(poster)
verification = {
    "passed": True, "output": str(output), "poster": str(poster),
    "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "video_frames": frames, "native_pal_fps": "13684/273", "video_time_base": "1/13684",
    "video_duration_ticks": end_ticks, "duration_seconds": end_ticks / 13684,
    "mci_start_frame": onset, "mci_start_seconds": onset * 273 / 13684,
    "mci_duration_seconds": 30, "mci_actual_native_fields": 1504,
    "last_video_packet_duration_ticks": 201,
    "audio_samples": audio_count, "audio_rate": 44100,
    "audio_duration_seconds": audio_count / 44100,
    "audio_video_duration_difference_seconds": abs(audio_count / 44100 - end_ticks / 13684),
    "source_disk_sha256": receipt["disk_sha256"],
    "source_capture_receipt": str(capture / "receipt.json"),
    "ffprobe": streams,
    "processing": "Actual consecutive VICE fields, nearest-neighbor 4x, native PAL timing. "
                  "Same-instance guest-clock audio cropped to MCI + 30 s. Only final field "
                  "duration shortened by 72/13684 s; no fade, freeze, temporal averaging, "
                  "audio fitting, or synthesized frames.",
    "ffmpeg_command": command,
}
output.with_suffix(".json").write_text(json.dumps(verification, indent=2) + "\n")
print(json.dumps({key: value for key, value in verification.items()
                  if key not in ("ffprobe", "ffmpeg_command")}, indent=2))
