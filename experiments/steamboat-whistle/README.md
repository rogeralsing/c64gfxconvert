# Approved Mickey GIF with sampled whistling

The current player uses the finished, cropped monochrome GIF: exactly the same
60 character screens, locked 256-glyph font, and six-second animation at 10 fps.
It reads the approved `mickey-gif/mono/darker/generated/` data directly. There is
no new rendering, cropping, thresholding, font training or character matching.
The original movie supplies audio only.

## Build and run

The ready-to-run program is [release/player.prg](release/player.prg). The
[VICE recording](release/c64-audio.wav) and [compact proof](release/verification.json)
are included alongside it.

On macOS, install RTK, FFmpeg, KickAssembler at `~/.local/bin/kickass`, and
VICE at `/opt/homebrew/bin/x64sc`. From the repository root:

```sh
rtk proxy python3 -m venv experiments/steamboat-whistle/.venv
rtk proxy experiments/steamboat-whistle/.venv/bin/python -m pip install -r experiments/steamboat-whistle/requirements.txt
rtk proxy experiments/steamboat-whistle/.venv/bin/python experiments/steamboat-whistle/build-gif-av.py
rtk proxy experiments/steamboat-whistle/.venv/bin/python experiments/steamboat-whistle/verify_gif_av.py --build experiments/steamboat-whistle/work/mickey-gif-av
```

Run `work/mickey-gif-av/player.prg` in PAL VICE with reSID, MOS8580 + digiboost.
The program loops with a short restart gap. All immutable picture, font and
audio inputs are bundled under `assets/`; no other worktree or temporary
analysis directory is required. The approved silent player remains unchanged.

## Audio and picture preservation

The approved screen bytes have SHA-256
`631fa988e77cf2713fc5ac38e8a4b54a5c69f2a4f89b035b27f4ef89344092aa`.
The font has SHA-256
`7fa677802cbea962c5530f0596bfe1e60dffccd6d3739ddd4cb0ff36aa06d5e6`.
The builder and verifier reject different data.

The soundtrack uses original movie time 29–37 seconds, compressed to six seconds
with FFmpeg `atempo=4/3`, preserving pitch. This is approximate pose matching:
the stylized GIF holds and redraws poses with different timing. Only audio is
retimed. The source receipt is `assets/source-audio.json`. Recorded absolute paths in
that receipt and the frozen source manifest are historical provenance only;
the builder reads the bundled assets.

SID3 plays 46,917 sample values at `985248/126 = 7819.428571 Hz` using the
Linus/SounDemoN sample-and-hold method. Four-bit indices occupy 23,459 clip bytes;
23,552 resident bytes include neutral padding. SID master volume stays 15.
Approved Hyperbased and Cream implementations are untouched.

The movie retains its 28,010-byte character delta stream and 2,048-byte font.
It draws directly to the front screen so sampling and all 60 frames fit the
CPU budget. Intermediate VIC fields contain transitions; completed screen
matrices are exact. This is not a claim that every scanned physical field is
identical to one complete source frame.

Native verification passes all 60 completed matrices, the complete SID sample
sequence, zero ring underruns, and true-drive startup restoring 62,122 RAM bytes.
Reports and actual VICE audio are under `work/mickey-gif-av/verification/`.
The cold-start packer restores the complete image before playback; there is no
LZ decompression while audio or video plays.

`build.py` / `player.asm` provide the reusable audio-only component. The
rejected original-movie visual experiment is excluded from this package.

## Sources

- [Source GIF](https://media.tenor.com/idROkHXXAjAAAAAM/mickey-steamboat-willie.gif)
- [Original movie, used only for audio](https://commons.wikimedia.org/wiki/File:Steamboat_Willie_(1928)_by_Walt_Disney.webm)
- [Linus Åkesson: Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php)
- [Preserved canonical music implementation](../sid-voice-sampler/README.md)
