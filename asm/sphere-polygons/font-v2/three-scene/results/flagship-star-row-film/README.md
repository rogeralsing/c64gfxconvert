# Independent raw-row film study

Each frame contains25 ordered row records: `startColumn8,length8,rawCharacters[length]`.
Only leading/trailing glyph0 is omitted. Internal zeros remain data; a blank row is `0,0`.
The binaries use relocatable little-endian16-bit byte offsets into `rows.bin`.

| Film | Raw glyphs | Row headers | Row data | Frame index | Direct row index |
|---|---:|---:|---:|---:|---:|
| original-pal-97 | 18032 | 4850 | 22882 | 194 | 4850 |
| baked-wave-2px-106 | 19036 | 5300 | 24336 | 212 | 5300 |

The two index columns are alternatives. Frame pointers need a scan through up to25 row
headers to reach a selected row. Direct row pointers locate any row immediately.
The proposed one-byte offsets relative to a frame fail: some row starts exceed255.
Two independently stored6-bit header fields require12bits, hence two byte-aligned bytes.
Even a combined code for all legal nonempty spans plus blank has821 states, exceeding one byte.

Every encoded frame roundtrips exactly through both index methods. The original film also
passes290 sinusoidal history composites, covering three loop closures and initially blank
histories, with no image-history buffers used by the host row fetches. The proof also uses
a500-byte runtime cache: ten histories ×25 rows ×2-byte row pointer, parsing the25 row
records only once per newly admitted film frame. Font bytes remain locked.

For the original97-frame film, the frame-index variant plus that row cache has this subtotal:
23076 movie/index +2048 font +1024 output screen +500 row-pointer cache =26648 bytes.
This avoids storing the4850-byte direct-row index for every frame. The cache concept is
host-proven; its native code, synchronization and speed have not been implemented.

Eleven existing history/work screens occupy11264 bytes. A hypothetical row renderer using
one output screen would use1024 screen bytes (10240 less); two screens would use2048
(9216 less). The row film and indexes are larger than the existing delta film. These are
allocation estimates only: native code, row-selection tables, scratch and FPS are unbuilt.
`fixedMemorySubtotals` in each study separates movie/index/font/screens and excludes those
unknown costs. Color RAM remains a separate allocation.

Run from the development checkout:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/study-row-film.py
```

`study.json` contains byte counts, hashes and proof summaries. Each dataset directory contains
the actual row stream, both valid alternative indexes, unchanged font and per-frame evidence.
The original dataset additionally contains `wave-composite-proof.json`.
