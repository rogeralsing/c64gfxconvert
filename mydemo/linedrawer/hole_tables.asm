// Each byte identifies the seven local decisions and absolute minor displacement mod 4.
*=$4000 "Exact line decision windows"
holeWindows:
.import binary "build/hole-windows.bin"
.var glyphTableSize = * - holeWindows
.assert "Window rows cover all viewport spans and 257 exact rates", * == holeWindows + 257*40, true

// The low byte of the decoder address is 54 times the starting minor
// coordinate. Four residue blocks plus a copy of the first three let the
// indexed load wrap all four possible starting positions without arithmetic.
.var decodedGlyphs = LoadBinary("build/hole-decoded.bin")
.const PHASE_BYTES = 7*54
.assert "Four complete alignment decoders", decodedGlyphs.getSize() == 4*PHASE_BYTES, true
*=$6900 "Major alignment 0"
phase0: .fill PHASE_BYTES, decodedGlyphs.get(i)
*=$6b00 "Major alignment 1"
phase1: .fill PHASE_BYTES, decodedGlyphs.get(PHASE_BYTES+i)
*=$9700 "Major alignment 2"
phase2: .fill PHASE_BYTES, decodedGlyphs.get(2*PHASE_BYTES+i)
*=$cd00 "Major alignment 3"
phase3: .fill PHASE_BYTES, decodedGlyphs.get(3*PHASE_BYTES+i)
.assert "Fourth decoder ends below I/O", * <= $d000, true
*=$6d00 "Block advance and slope pointers"
holeAdvance:
.for (var n=1; n<=3; n++) {
    .for (var i=0; i<64; i++) {
        .var pattern = (i & 7) | ((i >> 2) & 8)
        .var y = (i >> 3) & 3
        .for (var k=0; k<n; k++) { .eval y += (pattern >> k) & 1 }
        .byte ((y & 3) << 4) | (y >> 2)
    }
}
holeNormalizedKey: .import binary "build/hole-unsort.bin"
.assert "Window pointers remain page-aligned", ((* & $ff) == 0), true
holeWindowLo: .fill 256, <(holeWindows + 40*i)
holeWindowHi: .fill 256, >(holeWindows + 40*i)
.eval glyphTableSize += * - holeAdvance + decodedGlyphs.getSize()
.assert "Shift and rate tables fit below the walker", * <= $7000, true

// The 101 distinct oriented glyph rows occupy three unused RAM regions.
.var glyphs = LoadBinary("build/hole-glyph-rows.bin")
.var select = LoadBinary("build/hole-glyph-select.bin")
.function holeRow(index) {
    .if (index < 48) { .return $3a00 + 32*index }
    .if (index < 88) { .return $7700 + 32*(index-48) }
    .return $7d00 + 32*(index-88)
}
*=$3a00 "Oriented glyph rows 0..47"
.fill 48*32, glyphs.get(i)
*=$7700 "Oriented glyph rows 48..87"
.fill 40*32, glyphs.get(48*32 + i)
*=$7d00 "Remaining oriented glyph rows"
.fill glyphs.getSize()-88*32, glyphs.get(88*32 + i)
.eval glyphTableSize += glyphs.getSize()
.assert "Glyph rows end before depth reciprocals", * <= $8000, true
// Two westward Y-major loops invert the crossing bit before the address add.
// Reorder their glyph rows to accept the inverted keys directly.
*=$a000 "Full-block primary glyphs"
holeFullFirst:
.var unsort = LoadBinary("build/hole-unsort.bin")
.for (var o=0; o<8; o++) {
    .fill 64, glyphs.get(32*select.get(24+o)+(unsort.get(i ^ (o>=4 && (o&1) != 0 ? 32 : 0)) & 31))
}
.eval glyphTableSize += * - holeFullFirst
*=$be00 "Full-block secondary glyphs"
holeFullSecond:
.for (var o=0; o<8; o++) {
    .fill 64, glyphs.get(32*select.get(128+24+o)+(unsort.get(i ^ (o>=4 && (o&1) != 0 ? 32 : 0)) & 31))
}

.eval glyphTableSize += * - holeFullSecond

// Each valid endpoint layout loads its two glyphs using fixed addresses.
*=$b0a0 "Partial group glyph pairs"
.assert "Glyph routines follow rotated points", * >= $b000 + 6*MESH_VERTEX_COUNT, true
.var partialEntrypoints = List()
.for (var slot=0; slot<128; slot++) {
    .eval partialEntrypoints.add(*)
    .var offset = slot >> 5
    .var count = 1+((slot >> 3)&3)
    .if (offset+count <= 4 && count < 4) {
        ldx holeRow(select.get(slot)),y
        .if (count == 1) {
            jmp holeOnlyFirst
        } else {
            lda holeRow(select.get(slot+128)),y
            jmp holeDirectPair
        }
    }
}
holeTailDot:
.for (var minor=0; minor<4; minor++) {
    .for (var octant=0; octant<8; octant++) {
        .byte glyphs.get(32*select.get(octant) + 8*minor)
    }
}
.eval glyphTableSize += * - holeTailDot
.assert "Glyph routines fit below topology", * <= EDGES, true
*=$9e00 "Partial group dispatch"
holePartialJumps:
.assert "Partial dispatch fits an indexed low byte", (holePartialJumps & $ff) == 0, true
.for (var slot=0; slot<128; slot++) { .word partialEntrypoints.get(slot) }
.eval glyphTableSize += * - holePartialJumps

*=$68a0 "Stateless decoder start selectors"
phaseBias: .byte 0,54,108,162
phasePage: .byte >phase0, >phase1, >phase2, >phase3

.label assembledHoleGlyphBytes = glyphTableSize + (* - phaseBias)
.assert "Decoder helpers fit before phase 0", * <= phase0, true
