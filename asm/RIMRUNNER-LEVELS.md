# Rimrunner scenery maps

The original game keeps three scenery sets in RAM and reuses them across nine
levels. The background and the two lower tile bands use different native formats.
The extractor preserves their byte order and tile IDs; it does not turn a captured
40-column screen into a longer level.

## Native formats

| Band | Screen rows | Format |
| --- | --- | --- |
| Background | 5–16 | 12 rows of 80 character codes, in row order |
| Middle | 17–18 | Tile-ID list and 4×2-character tile definitions |
| Road | 19–20 | Character code zero; the raster background supplies its color |
| Foreground | 21–24 | Tile-ID list and 4×4-character tile definitions |

Each tile is four character columns wide. Its definition stores four bytes per
row: eight bytes for a middle tile, or sixteen for a foreground tile. A tile ID
of zero is valid. Map lengths are explicit; zero is not an end marker.

Character cells occupy 8×8 display pixels. The middle and foreground tiles
therefore occupy 32×16 and 32×32 display pixels respectively. Multicolor character
graphics retain the C64's horizontally doubled color pixels.

For horizontal character column `x`, the original lower-band reader selects
`map[x / 4]`, then column `x % 4` inside that tile. The background instead reads
its character map directly. Each band wraps independently at its own map width.

## Original addresses and level assignment

The three background maps are resident at `$1bc0`, `$1000`, and `$2780` for scenery
sets 0, 1, and 2 respectively. Each contains 960 bytes. Their far character sets
are resident at `$13c0`, `$4800`, and `$1f80` respectively.

| Set | Middle definitions / IDs | Middle width | Foreground definitions / IDs | Foreground width |
| --- | --- | --- | --- | --- |
| 0 | `$e23a` / `$e28a`, 52 IDs | 208 characters | `$e150` / `$e210`, 41 IDs | 164 characters |
| 1 | `$e3cd` / `$e45d`, 30 IDs | 120 characters | `$e2be` / `$e39e`, 47 IDs | 188 characters |
| 2 | `$e56b` / `$e5fb`, 42 IDs | 168 characters | `$e47b` / `$e5c3`, 55 IDs | 220 characters |

The background repeats after 80 character columns. These are genuine longer
maps: the two 40-column halves of each background differ.

The original level selector uses scenery sets `1, 0, 2, 1, 0, 2, 1, 0, 2` for
levels 1 through 9, then returns to level 1. The upper background colors are
`0, 4, 0, 11, 0, 6, 6, 2, 4`. A scenery set alone therefore does not identify a
level's complete palette.

The near character set combines a set-specific 1,328-byte prefix and a shared
720-byte suffix. The extractor records the resident source slots and hashes in
its manifest instead of assuming every resource contains a full independent font.

## Extraction

Use the original raw capture described in [RIMRUNNER.md](RIMRUNNER.md):

```sh
rtk proxy python3 asm/tools/extract-rimrunner-levels.py \
  --ram asm/build/research/rimrunner/extracted/captures/raster-00/ram.bin \
  --output asm/build/rimrunner-levels
```

The output retains native character maps, tile-ID lists, tile definitions, and
character sets, with a manifest and PNG previews. Original graphics and generated
files remain local ignored build artifacts.

The earlier character-based parallax demo used scenery set 1, reading the
background map directly and expanding incoming columns from the native tile maps.
The current [parallax demo](PARALLAX.md) instead uses supplied MCI scenery. The
extractor and native map data remain available for character-based experiments.

## Evidence and scope

Original initialization at `$9f64` reads ten tile IDs. `$9f8e` selects a definition
with an eight- or sixteen-byte stride, and `$9faf` writes four character codes per
row. Scroll readers at `$9c59`, `$9c62`, and `$9c7b` select individual incoming
tile columns. `$9e95` reads the circular background window.

Independent expansion of set 1's first ten tiles matched all 80 middle-band and
160 foreground character codes in the original screen RAM, with no differences.
The recovered scenery formats and level assignments do not include enemy waves,
generator state, collision behavior, or other gameplay objects.
