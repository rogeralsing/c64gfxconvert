# Mathematical finite lines over binary character fill

This is a bounded host prototype, not a native animation player. It generates
reusable mathematical line masks and serializes finite line commands for the
current smooth 64-frame checker motion. It does not store captured glyph chains
in the line lookup. No native execution time, machine-code size, or frame rate
is claimed here.

The experiment is not a compression winner. The smallest exact edge-only movie
is 36,061 bytes before the common 2,048-byte font. Keeping the existing static
circle remap in the approximate decoder increases that exact movie to 44,985
bytes. The existing 19,096-byte HC64 movie and the separately measured delta
player remain better storage choices for this motion.

Run from `asm/sphere-polygons`:

```sh
rtk proxy node precomputed/hybrid/lines/geometry-lines.cjs
```

The ignored `build/geometry-report.json` contains every frame's sizes, character
and glyph-dot differences, spill counts, source hashes, and serialized movie
hashes. `*-exact.gl64` and `*-approximate.gl64` are actual standalone selection
data streams. The fixed font is `build/font.bin`, outside those streams.

## Mathematical line primitive

`createTables(q, glyphLut)` generates masks from the eight existing character
probe positions. The supported grids are `q=8` and `q=16`. A line chooses its
major axis and a normalized signed minor slope `n/q`, with `-q <= n <= q`.
Fractional start phase is one of `q` positions per character. The mask table
contains the `>=` and `==` comparisons for each probe, both major axes, and
three neighboring minor cells. Table generation does not inspect the movie.

For a probe at local major/minor coordinates, the integer comparison is:

```text
q * minor - n * major - phase * 8
```

Each major character step adds `n` to phase, carrying a minor-cell step when
phase crosses `q`. Opposite fill polarity and strict/inclusive equality use the
same tables. `maskAt()` exposes the half-plane operation.
`lineGlyphSequence()` walks only the finite boundary neighborhood and returns
partial character masks and their fixed-font glyph selections. There is no
320-by-200 runtime source bitmap and no per-character search through font pixels.

The generated mask tables cost 1,632 bytes for Q8 or 6,336 bytes for Q16. Both
reuse the 256-byte mask-to-glyph lookup. An isolated line therefore needs 1,888
or 6,592 bytes of selection tables, plus the common font and drawer code.

## Fill, corners, and finite edges

Each frame decodes the existing wildcard PackBits on/off fill. The 475-cell
circle layout uses an average 57.46875 bytes of compressed fill per frame.
White-face visibility takes five bytes. Each visible white polygon contributes
three or four line commands, averaging 66 lines per frame, with a range of
62–70. The finite command stream averages 269 bytes per frame.

`decodeEdgeOnly()` follows the finite boundary of each line, restricted to the
circle character layout. It gathers approximately 222 candidate cells per
frame. At each candidate it ANDs the planes of each white owning face whose
finite bounds reach that cell, then ORs those face contributions. This handles
shared vertices and cells containing several edges before selecting a glyph.
A later glyph write cannot erase an earlier white contribution. Other cells
retain their decoded binary fill.

The bounding test is derived from the serialized finite line bounds and line
phase; projected vertex arrays are not a decoder input. The measured total is
approximately 3,089–3,091 line-mask operations per frame, including candidate
discovery and all owner-plane tests. Full-polygon baseline modes in the report
evaluate all 475 cells and are not the proposed edge-only player.

The optional final silhouette pass applies the existing fixed-font remap to the
complete composed screen, including binary fill cells. This costs 9,728 shared
bytes: 256-byte compact map, 8,880-byte remap, and 592-byte records. It produces
zero lit dots outside the strict radius-94 circle across all 64 approximate
frames. Raw approximate outputs spill and should not be treated as visually
acceptable substitutes when the silhouette must remain strict.

## Actual serialized format

The three-byte line descriptor is a little-endian 24-bit word:

| Bits | Meaning |
| --- | --- |
| 0–9 | Anchor character offset, 0–999 |
| 10–13 | Fractional phase; 0–7 or 0–15 |
| 14–19 | Signed slope encoded as `n + q` |
| 20 | Major axis, X or Y |
| 21 | Positive or negative minor half-plane |
| 22 | Include the equality boundary |
| 23 | Reserved zero |

The fourth byte has two nibbles: major cells before and after the anchor. The
encoder includes a one-character margin beyond each projected endpoint. Face
order and edge counts come from the serialized 36-byte white-face count table;
there is no free per-frame topology table.

Each GL64 movie starts with this 18-byte header:

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | ASCII `GL64` |
| 4 | 1 | Version, 1 |
| 5 | 1 | Q grid, 8 or 16 |
| 6 | 1 | Bit 0: circle-remap data present |
| 7 | 1 | Frame count, 64 |
| 8 | 1 | White-face count, 36 |
| 9 | 1 | Character-row count, 25 |
| 10 | 2 | Little-endian `>=` table length |
| 12 | 2 | Little-endian equality table length |
| 14 | 2 | Circle-remap length, zero if absent |
| 16 | 2 | Circle-record length, zero if absent |

The header is followed by face counts, 50 bytes of `[start,count]` row layout,
the 256-byte glyph lookup, both mathematical mask tables, and optional compact
map/remap/records. Every frame then has three little-endian 16-bit lengths for
line, fill, and exception payloads, followed by those payloads. An exception
payload is a 16-bit count followed by three bytes per correction: 16-bit screen
offset and glyph byte. Approximate movies carry the two-byte zero count.

`decodeMovie()` reconstructs the layout, topology, lookup tables, circle data,
fill, line commands, and corrections from the movie bytes. It rejects trailing
or truncated data. The study compares all 64 decoded exact screens with the
reference and every approximate decoded screen with its predicted output.
The reported total is asserted equal to the actual serialized file length.

## Measured 64-frame result

Motion is yaw 0–59.0625 degrees in 0.9375-degree steps, fixed pitch 22 degrees
and roll 12 degrees. The 60-degree checker symmetry closes the loop. Each number
below includes the actual movie header, shared selection tables, row metadata,
all frame lengths, fill, finite commands, and exception counts. Add 2,048 bytes
for the common font. Native drawer/decoder code and native working RAM have not
been implemented or measured by this host experiment.

| Variant | Shared bytes | Approx. movie | Exact movie | Changed chars/frame | Different glyph dots/frame | Approx. outside dots/frame |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Q8 raw | 1,992 | 23,398 | 36,814 | 69.875 | 1,032.281 | 20.188 |
| Q16 raw | 6,696 | 28,102 | 36,061 | 41.453 | 569.016 | 16.984 |
| Q8 circle remap | 11,720 | 33,126 | 45,930 | 66.688 | 988.578 | 0 |
| Q16 circle remap | 16,424 | 37,830 | 44,985 | 37.266 | 520.516 | 0 |

Glyph-dot differences compare actual chosen 8-by-8 font rows with the existing
movie, not with an ideal continuous sphere. The strict circle contains 27,729
dots. Q16 with remap differs on approximately 1.88% of that area; Q8 with remap
differs on approximately 3.57%. All exact patched outputs are byte-identical to
the existing 1,000-character screens and have zero outside-circle dots.

The descriptor approximation, finite candidates, and fixed-font resolution
produce exceptions at corners and near the limb. This version records them
explicitly rather than claiming that independently drawn lines reconstruct
every original glyph. The format is functional and reusable, but its repeated
per-frame commands and correction payloads cost more than direct movie coding.

## Reproduction identity

The report records SHA-256 for the experiment source, motion generator, raster,
mesh, native-model resolver, fill codec, layout helper, font, reference screens,
and each exact GL64 movie. At this snapshot:

```text
geometry-lines.cjs f1918910a964382a77dfecf77650ebd55966b9ba2b1eeee89c9971e92c5986c5
reference.bin      5d4b75fc49e0401709f230e7a6dd61cb1efb7f1c2d695ee8edba02b80029cbce
font.bin           54738b614baf5a56ac4c74fa33496e6148273f798a703fee62a02fe6fed80769
q16-edge-raw-exact b9c5de6f6d6d27025106d81235f41e5dbca76ac6074e569ad4eafcaf990a6319
```

The parent experiment may separately encode temporal changes in these command
bytes. That is a distinct storage layer; no temporal savings are included here.
