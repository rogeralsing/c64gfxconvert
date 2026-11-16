# Complete Giana recording

The [opening-animation preview](intro-opening-tv.gif) shows small Giana collecting
the beachball and transforming into punk Giana. Its [capture data](intro-opening-tv.json)
records the source identity and native verification. The full video below
preserves the earlier four-stage version before this opening was added.

[Watch the video with sound](giana-complete-mci-30s.mp4).

The historical recording includes both levels in both rooms, the disk loading transition,
and 30 seconds of the full-screen MCI picture with the continuing original SID
music. Its total duration is 3:14.43. The MP4 contains H.264 video at 1280×800
and mono AAC audio at 44.1 kHz.

[Verification data](giana-complete-mci-30s.json) records the video and source
hashes, field counts, guest-clock audio checks, and exact ending time.
[The poster](giana-complete-mci-30s.png) shows the initial room.

## Capture and export

Requirements: the normal Giana build dependencies, PAL VICE (`x64sc`), Python
with Pillow, and FFmpeg/ffprobe with libx264 and AAC support. Run from the
repository root:

```sh
rtk proxy ./giana/build.sh
rtk proxy python3 giana/tools/capture-video.py --name complete-demo-mci30
rtk proxy python3 giana/tools/encode-video.py giana/build/video/complete-demo-mci30
```

`VICE` or the capture command's `--emulator` option selects the VICE executable.
Each capture needs a fresh output name. Raw PNGs, WAV audio, logs, and detailed
capture receipts remain under the ignored `giana/build/video/` directory. The
export writes `giana/build/video/giana-complete-mci-30s.mp4`, its poster, and its
verification JSON; `--output` selects another MP4 path.

Capture boots the real D64 with true 1541 emulation and saves each completed
PAL field together with audio from the same emulator. Image and PCM boundaries
use the C64 guest clock. The export crops the 320×200 active picture and scales
it by four with nearest-neighbor sampling.

The video retains the native PAL cadence of 13,684/273 fields per second.
The MCI picture starts at field 8,242 and alternates its two actual fields for
1,504 fields. The export shortens the final field by 72 ticks at time base
1/13,684, making the MCI interval exactly 30 seconds. The audio ends at the
nearest 44.1 kHz sample, within 1.15 microseconds of the video end.

The encoder checks both MCI phases against the tracked original field images,
all video packet timestamps and durations, the audio sample count, and a full
decode of the finished MP4. The recorded demo comes from source commit
`8ae53416be49e91ae73e5d0a7e315d582d80e046`.
