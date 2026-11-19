// Accumulate the original line masks, then resolve each occupied cell once.
.const compactMasksLo = $c600
.const compactMasksHi = $ca00
.const compactPatchLimit = 256 - COMPACT_FIRST_PATCH

.label compactCellLo = $ee
.label compactCellHi = $f0
.label compactRow = $f6
.label compactFirstColumn = $f7
.label compactColumn = $f8
.label compactAfterColumn = $f9
.label compactLastRow = $fa

*=$7800 "Compact join renderer"
compactInit:
    lda #0
    sta compactOverflow
    tax
!clear:
    .for (var page = 0; page < 4; page++) {
        sta compactMasksLo + page * 256,x
        sta compactMasksHi + page * 256,x
    }
    inx
    bne !clear-
    rts

// X is a glyph code in the original line bank, jptrLo/Hi its screen cell.
// Both screen bases are page-aligned, so the low address byte is unchanged.
compactStamp:
    lda jptrLo
    sta compactCellLo
    sta compactCellHi
    lda jptrHi
    sec
    sbc baseHi
    clc
    adc #>compactMasksLo
    sta compactCellLo+1
    adc #>(compactMasksHi - compactMasksLo)
    sta compactCellHi+1
    ldy #0
    lda REVLO,x
    ora (compactCellLo),y
    sta (compactCellLo),y
    lda REVHI,x
    ora (compactCellHi),y
    sta (compactCellHi),y
    rts

// All clipped lines lie within the current bounds. Clear shadow cells as
// they are emitted so the next frame starts with an empty accumulation.
flushCompact:
    lda #0
    sta compactOverflow
    lda boxMinX
    lsr
    lsr
    sta compactFirstColumn
    lda boxMaxX
    lsr
    lsr
    clc
    adc #1
    sta compactAfterColumn
    lda boxMinY
    lsr
    lsr
    sta compactRow
    lda boxMaxY
    lsr
    lsr
    sta compactLastRow
!row:
    ldx compactRow
    lda charRowLo,x
    sta compactCellLo
    sta compactCellHi
    sta jptrLo
    lda charRowHi,x
    clc
    adc #>compactMasksLo
    sta compactCellLo+1
    adc #>(compactMasksHi - compactMasksLo)
    sta compactCellHi+1
    lda charRowHi,x
    clc
    adc baseHi
    sta jptrHi
    ldy compactFirstColumn
!column:
    lda (compactCellLo),y
    sta patLo
    lda (compactCellHi),y
    sta patHi
    ora patLo
    beq !next+
    lda #0
    sta (compactCellLo),y
    sta (compactCellHi),y
    sty compactColumn
    jsr compactGlyphCode
    ldy compactColumn
    sta (jptrLo),y
!next:
    iny
    cpy compactAfterColumn
    bne !column-
    lda compactRow
    cmp compactLastRow
    beq !done+
    inc compactRow
    jmp !row-
!done:
    rts

// The mask's high byte and half of its low byte select a displacement.
// The generator reserves disjoint ranges for both halves with the same
// high-byte tag, so the tag comparison also rejects every unknown mask.
.macro ProbeCompactHash(halfOffset) {
    clc
    adc compactHashDispLo + halfOffset,x
    tay
    lda compactHashDispHi + halfOffset,x
    adc #0
    and #$ef                  // wrap $f0 to $e0 at the end of the hash
    sta readTag+2
readTag:
    ldx $e000,y
    cpx patHi
    bne compactHashMiss
    ora #$10
    sta readCode+2
readCode:
    lda $f000,y
    rts
}

compactLookupGlyph:
    ldx patHi
    lda patLo
    bmi !upper+
    ProbeCompactHash(0)
!upper:
    and #$7f
    ProbeCompactHash($100)
compactHashMiss:
    lda #0
    rts

compactGlyphCode:
    jsr compactLookupGlyph
    bne !done+
    ldx #0
!scan:
    cpx JCOUNT
    beq !new+
    txa
    asl
    tay
    lda JOINTT,y
    cmp patLo
    bne !next+
    lda JOINTT+1,y
    cmp patHi
    beq !code+
!next:
    inx
    bne !scan-
!new:
    cpx #compactPatchLimit
    bcs compactOverflowGlyph
    txa
    asl
    tay
    lda patLo
    sta JOINTT,y
    lda patHi
    sta JOINTT+1,y
    inc JCOUNT
    txa
    pha
    jsr patchGlyph
    pla
    tax
!code:
    txa
    clc
    adc #COMPACT_FIRST_PATCH
!done:
    rts

// Unmeasured poses may use more patterns than the patch bank holds.
// Keep a mapped portion of the cell and count such fallbacks for testing.
compactOverflowGlyph:
    inc compactOverflow
!simplify:
    lda patLo
    beq !upper+
    sec
    sbc #1
    and patLo
    sta patLo
    jmp !test+
!upper:
    lda patHi
    sec
    sbc #1
    and patHi
    sta patHi
!test:
    lda patLo
    ora patHi
    beq !done+
    jsr compactLookupGlyph
    beq !simplify-
!done:
    rts

compactOverflow:
.byte 0
.assert "Compact renderer fits before projection", * <= $7c00, true

*=HASHKL "Compact glyph hash offsets"
compactHashDispLo:
.import binary "build/compact-hash-disp-lo.bin"
compactHashDispHi:
.import binary "build/compact-hash-disp-hi.bin"
.assert "Compact hash offsets fit before legacy glyph codes", * == HASHV, true

*=$e000 "Compact glyph hash tags under KERNAL"
.import binary "build/compact-hash-tags.bin"
.assert "Compact hash tags occupy exactly 16 pages", * == $f000, true
.import binary "build/compact-hash-codes.bin"
.assert "Compact glyph codes end before interrupt vectors", * == $fffa, true
