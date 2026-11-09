# Bounded shared H/V motif study

The exact 64-frame smooth checker movie serializes to **18,969 bytes** with this
format. That is only 127 bytes below the 19,096-byte independent HC64 movie and
3,800 bytes above the 15,169-byte previous-image HD64 movie. The independent
format remains simpler; this H/V-only study does not demonstrate a substantial
replacement for its raw edge glyphs.

Four shared motifs occupy **38 bytes**, including the dictionary count and
entry lengths. They are used in 17–34 distinct frames each, rather than being
dictionary entries for individual frames. The 119 three-byte line commands
cover **586 of 11,260 edge cells** (5.2%); the other 10,674 edge glyphs remain
exact literal exceptions. Commands actually use nonzero sequence phases 113
times and reverse a sequence 112 times. Filled-side polarity is part of the
stored glyph codes; no uncounted inversion table or new font is assumed.

The actual empty-dictionary control costs 19,161 bytes: the HC64 baseline plus
one command-count byte per frame and one shared dictionary-count byte. Motifs
save 229 bytes after their command costs, then their 37 entry bytes, producing
192 bytes of savings against that control and 127 against HC64.

## Reuse and bounded search

The encoder collects contiguous horizontal and vertical edge-cell sequences
of length4–16. A sequence and its reverse share a dictionary candidate; suffix
phases can reuse a longer sequence. Candidates must provide usable occurrences
in at least three distinct training frames. At most256 recurrent candidates
are considered, and at most64 entries can be selected. Greedy selection charges
three bytes per line command plus the whole shared entry before accepting it.
The result is a bounded heuristic, not a global compression optimum.

These are recurring exact glyph sequences. They are not universal mathematical
line tables indexed by angle, nor prepared complete character screens. Diagonal
lines are represented through any matching H/V pieces and literal exceptions;
no uncounted diagonal path data is presumed.

## Serialized LM64 format

The container contains all of the following:

- Twelve-byte global header: `LM64`, version1, width40, height25, frame countLE16,
  layout2, fill codec1, reserved0.
- Fifty row-layout bytes, shared once.
- Dictionary count8, followed by each entry's length8 and raw glyph sequence.
- For each frame, fillLengthLE16 and edgeLengthLE16, then both byte payloads.

Fill is the existing wildcard-optimized PackBits bitfield, expanding to60 bytes
for475 cells; its total is3,678 bytes. The edge payload starts with commandCount8
and then three bytes per command:

| Field | Encoding |
| --- | --- |
| Start cell | Word bits0–9 |
| Vertical, rather than horizontal | Word bit10 |
| Sequence phase | Word bits11–14 |
| Reserved | Word bit15=0 |
| Motif ID | Third byte bits0–5 |
| Reverse stored sequence | Third byte bit6 |
| Reserved | Third byte bit7=0 |

The line copies `entry.length − phase` glyphs, starting at that phase of the
forward or reversed sequence. Destination steps are1 or40. This is an actual
precomputed sequence copier, requiring no runtime geometry. After all commands
come a fixed60-byte residual presence mask and one raw glyph per set bit in
raster order. Command cells and residual cells cannot overlap. Non-edge output
cells are untouched. All command bytes, residual map bytes, raw glyphs and
shared entry lengths are included in the measured total. The font's2,048 bytes
remain separate, as in both comparison formats.

## API and proof

`dictionary-lines.cjs` exports `buildDictionary`, `createEdgeCodec`, `serialize`,
`deserialize`, and `study`. The edge codec uses `encode(screen)` and
`decode(payload, output)` with `requiresLayout: 'circle'`. Serialization embeds
the shared entries; deserialization reads them back from the actual bytes.

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/lines/dictionary-lines.cjs
```

Outputs are `build/dictionary-lines.lm64` and `build/dictionary-report.json`.
All64 reconstructed1,000-byte screens matched exactly. Another64,000 output
cells verified that edge decoding preserves arbitrary background values. Three
synthetic frames and hand-written command bytes independently checked forward,
reverse, nonzero phase, vertical stepping, empty/solid fill and literal
exceptions. The empty-dictionary control also round-tripped exactly.

The LM64 SHA-256 is
`07eff5ded02bf85dc41cb357efa3a4737cf0c4dbc18b5015cd9d478d6aa556ec`.
This is a host packing/decoding result; no native player speed is claimed.
