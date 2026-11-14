# Original-film calibration

This isolated study uses continuous, forward frames and matching audio from the
same original Steamboat Willie WebM timeline. It preserves the accepted GIF
assets and released C64 player.

The source interval is 32–38 seconds: 60 frames at 10 fps, with six seconds of
unretimed audio. Native source frames are 1296 × 1080 RGB. Contrast is applied
before crop and area scaling. The current crop is x54, y166, width 1224,
height 874; the 300 × 200 image is centered in a 320 × 200 bitmap.

Run from the repository root with the experiment's Python dependencies and
FFmpeg available:

```sh
rtk proxy python3 experiments/steamboat-whistle/original-study/prepare-original.py \
  --input /absolute/path/to/Steamboat_Willie.webm
rtk proxy python3 experiments/steamboat-whistle/original-study/prepare-bitmaps.py
rtk proxy python3 experiments/steamboat-whistle/original-study/prepare-outlines.py
rtk proxy python3 experiments/steamboat-whistle/original-study/build-preview.py --default outlines
```

Generated files stay under `../work/original-calibration/`. `source/source.json`
records original timestamps, hashes and an independent audio-timeline check.
The preview compares an accepted GIF still with the original-derived bitmap
before character mapping. Its audio comes from the same original interval.

The original movie contains scenery absent from the simplified GIF. Global
contrast trades background removal against thin line retention; the comparison
keeps several settings visible for that reason.

The selected outline variant uses native black/white levels 15/95, a centered
5 × 5 minimum filter at native resolution, area scaling and binary threshold 128.
This strengthens the original ink before reduction; it does not redraw shapes.
The comparison also retains a per-frame exposure variant, derived from each
source frame's ink and paper percentiles. The fixed-level outline variant gave
the better observed balance of line continuity and background suppression.

[Original source](https://commons.wikimedia.org/wiki/File:Steamboat_Willie_(1928)_by_Walt_Disney.webm)

## Native C64 movie with sampled sound

`convert-chars.py` fits one 256-character monochrome font to these original-film
bitmaps. `build-player.py` combines the character deltas with the matching
six-second soundtrack using the existing Linus-style SID sampler. The new
runtime preserves that sampler and accelerates short cursor literals. The
accepted GIF implementation remains separate.

After source calibration, build and verify the original-film player:

```sh
rtk proxy python3 experiments/steamboat-whistle/original-study/convert-chars.py
rtk proxy python3 experiments/steamboat-whistle/original-study/build-player.py --no-loop
rtk proxy python3 experiments/steamboat-whistle/original-study/verify-player.py \
  --build experiments/steamboat-whistle/work/original-c64/player-final
rtk proxy python3 experiments/steamboat-whistle/original-study/capture-video.py \
  --build experiments/steamboat-whistle/work/original-c64/player-final \
  --output experiments/steamboat-whistle/work/original-c64/capture \
  --audio experiments/steamboat-whistle/work/original-c64/player-final/verification/all.wav
```

Use a Python environment with the experiment's requirements installed.
`verify-player.py` checks source identity, true-drive cold loading, all completed
screen matrices, native draw deadlines, every SID sample and ring-buffer timing.
`capture-video.py` records actual VIC-II PAL fields and muxes the matching native
VICE recording. It does not reconstruct video from the exported screen data.
The recording retains visible transitions while the front screen is being drawn.
