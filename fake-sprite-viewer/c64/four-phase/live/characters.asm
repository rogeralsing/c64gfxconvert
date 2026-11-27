.const LIVE_CHAR_ERASE_CODE = $6000
.const LIVE_CHAR_BLEND_CODE = $4000
.const LIVE_CHAR_POSITION_DATA = $6800
.const LIVE_CHAR_SCREEN_WIDTH = 40
.const LIVE_CHAR_TILE_SIZE = 3
.const LIVE_CHAR_TILE_BYTES = LIVE_CHAR_TILE_SIZE * LIVE_CHAR_TILE_SIZE

.label liveCharPage = $20
.label liveCharX = $22
.label liveCharFront = $24
.label liveCharNextScratch = $27
.label liveCharFootprintNext = $29
.label characterOverflow = $2b
.label liveCharUnder = $f3
.label liveCharOutput = $f5
.label liveCharScreenPointer = $f9
.label liveCharPhaseByY = LIVE_CHAR_POSITION_DATA
.label liveCharRowLo = LIVE_CHAR_POSITION_DATA + $100
.label liveCharRowHi = LIVE_CHAR_POSITION_DATA + $200
.label liveCharGlyphPageA = LIVE_CHAR_POSITION_DATA + $300
.label liveCharGlyphPageB = LIVE_CHAR_POSITION_DATA + $400

.function liveCharKeepMask(byte) {
    .var mask = 0
    .for (var shift = 0; shift < 8; shift += 2) {
        .var pair = 3 << shift
        .if ((byte & pair) == 0) {
            .eval mask = mask | pair
        }
    }
    .return mask
}

.function liveCharCovers(glyph) {
    .var blackPixels = 0
    .for (var row = 0; row < 8; row++) {
        .var byte = font.get(glyph * 8 + row) & $ff
        .for (var shift = 0; shift < 8; shift += 2) {
            .if ((byte & (3 << shift)) == 0) {
                .eval blackPixels++
            }
        }
    }
    .return blackPixels <= 1
}

.macro liveStampTile(phase) {
    lda #liveCharEraseOffsets.get(phase)
    sta liveCharOldEraseLo,x
    .for (var row = 0; row < LIVE_CHAR_TILE_SIZE; row++) {
        .for (var col = 0; col < LIVE_CHAR_TILE_SIZE; col++) {
            .var glyph = tiles.get(phase * LIVE_CHAR_TILE_BYTES + row * LIVE_CHAR_TILE_SIZE + col)
            .if (glyph != 0) {
                ldy #(row * LIVE_CHAR_SCREEN_WIDTH + col)
                .if (liveCharCovers(glyph)) {
                    lda #glyph
                    sta (liveCharScreenPointer),y
                } else {
                    lda (liveCharScreenPointer),y
                    beq !empty+
                    ldx #glyph
                    jsr liveMergeCharacterCell
                    jmp !done+
!empty:
                    lda #glyph
                    sta (liveCharScreenPointer),y
!done:
                }
            }
        }
    }
    rts
}

// Arrange masks in subset chains so each handler falls through the shared suffix.
.function liveCharEraseCellCount(mask) {
    .var count = 0
    .for (var cell = 0; cell < LIVE_CHAR_TILE_BYTES; cell++) {
        .if ((mask & (1 << cell)) != 0) {
            .eval count++
        }
    }
    .return count
}

.function liveCharLargestEraseSubset(masks, available, parent) {
    .var best = -1
    .var bestSize = -1
    .for (var index = 0; index < masks.size(); index++) {
        .var mask = masks.get(index)
        .if ((available & (1 << index)) != 0 && (mask & parent) == mask) {
            .var size = liveCharEraseCellCount(mask)
            .if (size > bestSize) {
                .eval best = index
                .eval bestSize = size
            }
        }
    }
    .return best
}

.var liveCharPhaseMasks = List()
.var liveCharMasks = List()
.for (var phase = 0; phase < 16; phase++) {
    .var phaseMask = 0
    .for (var cell = 0; cell < LIVE_CHAR_TILE_BYTES; cell++) {
        .if (tiles.get(phase * LIVE_CHAR_TILE_BYTES + cell) != 0) {
            .eval phaseMask = phaseMask | (1 << cell)
        }
    }
    .eval liveCharPhaseMasks.add(phaseMask)
    .var known = false
    .for (var index = 0; index < liveCharMasks.size(); index++) {
        .if (liveCharMasks.get(index) == phaseMask) {
            .eval known = true
        }
    }
    .if (!known) {
        .eval liveCharMasks.add(phaseMask)
    }
}

.var liveCharEraseOrder = List()
.var liveCharEraseSegments = List()
.var liveCharEraseTails = List()
.var liveCharEraseUniqueOffsets = List()
.var liveCharEraseOffsets = List()
.var liveCharEraseOffset = 0
.var liveCharUnplacedEraseMasks = (1 << liveCharMasks.size()) - 1
.var nextEraseMask = -1
.for (var step = 0; step < liveCharMasks.size(); step++) {
    .if (nextEraseMask == -1) {
        .eval nextEraseMask = liveCharLargestEraseSubset(liveCharMasks, liveCharUnplacedEraseMasks, $1ff)
    }
    .var mask = liveCharMasks.get(nextEraseMask)
    .eval liveCharUnplacedEraseMasks = liveCharUnplacedEraseMasks ^ (1 << nextEraseMask)
    .eval nextEraseMask = liveCharLargestEraseSubset(liveCharMasks, liveCharUnplacedEraseMasks, mask)
    .var oldMask = 0
    .if (nextEraseMask != -1) {
        .eval oldMask = liveCharMasks.get(nextEraseMask)
    }
    .var segment = mask ^ oldMask
    .eval liveCharEraseOrder.add(mask)
    .eval liveCharEraseUniqueOffsets.add(liveCharEraseOffset)
    .eval liveCharEraseSegments.add(segment)
    .eval liveCharEraseTails.add(nextEraseMask == -1)
    .eval liveCharEraseOffset += liveCharEraseCellCount(segment) * 3 + (nextEraseMask == -1 ? 3 : 0)
}
.for (var phase = 0; phase < 16; phase++) {
    .for (var index = 0; index < liveCharEraseOrder.size(); index++) {
        .if (liveCharEraseOrder.get(index) == liveCharPhaseMasks.get(phase)) {
            .eval liveCharEraseOffsets.add(liveCharEraseUniqueOffsets.get(index))
        }
    }
}
.errorif liveCharEraseOffset > $100, "Live erase routines must fit one dispatch page"

// Both targets start blank.
initCharacters:
    lda #0
    sta liveCharVisited
    sta liveCharVisited + 1
    ldx #0
!clear:
    .for (var page = 0; page < 3; page++) {
        sta SCREEN_A + page * $100,x
        sta SCREEN_B + page * $100,x
    }
    inx
    bne !clear-
    ldx #231
!tail:
    sta SCREEN_A + $300,x
    sta SCREEN_B + $300,x
    dex
    cpx #$ff
    bne !tail-
    rts

// A is the target screen page. X is the matching charset page.
beginCharacterFrame:
    sta liveCharPage
    lda #>liveCharGlyphPageA
    cpx #>CHARSET
    beq liveCharSelectGlyphTable
    lda #>liveCharGlyphPageB
liveCharSelectGlyphTable:
    sta liveCharUnderPageLookup + 2
    sta liveCharScratchPageLookup + 2
    lda #FIXED_CHARS
    sta liveCharNextScratch
    lda #0
    sta characterOverflow

    ldx #0
    ldy #0
    lda liveCharPage
    cmp #>SCREEN_A
    beq liveCharSelectFootprints
    ldx #BALL_COUNT
    iny
liveCharSelectFootprints:
    stx liveCharFootprintNext
    lda liveCharVisited,y
    beq liveCharFirstVisit

liveCharClearFootprints:
    txa
    clc
    adc #BALL_COUNT
    sta liveCharClearLimit + 1
    lda #0
liveCharClearNext:
    ldy liveCharOldEraseLo,x
    sty liveCharEraseCall + 1
    ldy liveCharOldEraseHi,x
    sty liveCharEraseCall + 2
    // The erase routine indexes all its stores from the saved low screen address.
    ldy liveCharOldLo,x
liveCharEraseCall:
    jmp LIVE_CHAR_ERASE_CODE
liveCharEraseContinue:
    inx
liveCharClearLimit:
    cpx #0
    bne liveCharClearNext
liveCharClearDone:
    rts

liveCharFirstVisit:
    lda #1
    sta liveCharVisited,y
    rts

// A is wide-pixel X and Y is raster Y. Draw balls back to front.
drawCharacterBall:
    sta liveCharX
    and #3
    ora liveCharPhaseByY,y
    tax
    lda liveCharStampLo,x
    sta liveCharStampCall + 1
    lda liveCharStampHi,x
    sta liveCharStampCall + 2

    lda liveCharX
    lsr
    lsr
    clc
    adc liveCharRowLo,y
    sta liveCharScreenPointer
    lda liveCharRowHi,y
    adc liveCharPage
    sta liveCharScreenPointer + 1
    ldx liveCharFootprintNext
    // Screen pages $28–$2f map to erase code pages $60–$67.
    eor #>(SCREEN_A ^ LIVE_CHAR_ERASE_CODE)
    sta liveCharOldEraseHi,x
    lda liveCharScreenPointer
    sta liveCharOldLo,x
    inc liveCharFootprintNext
liveCharStampCall:
    jmp liveCharStampRoutines

// A is the back code, X the fixed front code, and Y the relative screen offset.
liveMergeCharacterCell:
    stx liveCharFront
    cmp liveCharFront
    beq liveCharMergeDone
    tax
    lda liveCharGlyphLo,x
    sta liveCharUnder
liveCharUnderPageLookup:
    lda liveCharGlyphPageA,x
    sta liveCharUnder + 1
    cpx #FIXED_CHARS
    bcs liveCharReuseScratch

    // A scratch code of zero means the counter has wrapped past glyph 255.
    ldx liveCharNextScratch
    beq liveCharNoScratch
    inc liveCharNextScratch
    txa
    sta (liveCharScreenPointer),y
    lda liveCharGlyphLo,x
    sta liveCharOutput
liveCharScratchPageLookup:
    lda liveCharGlyphPageA,x
    sta liveCharOutput + 1
    jmp liveCharBlend

liveCharReuseScratch:
    lda liveCharUnder
    sta liveCharOutput
    lda liveCharUnder + 1
    sta liveCharOutput + 1
liveCharBlend:
    ldx liveCharFront
    lda liveCharBlendLo,x
    sta liveCharBlendCall + 1
    lda liveCharBlendHi,x
    sta liveCharBlendCall + 2
liveCharBlendCall:
    jmp LIVE_CHAR_BLEND_CODE
liveCharMergeDone:
    rts
liveCharNoScratch:
    lda #1
    sta characterOverflow
    lda liveCharFront
    sta (liveCharScreenPointer),y
    rts

.var liveCharStampAddresses = List()
liveCharStampRoutines:
    .for (var phase = 0; phase < 16; phase++) {
        .eval liveCharStampAddresses.add(*)
        :liveStampTile(phase)
    }
liveCharStampLo: .fill 16, <liveCharStampAddresses.get(i)
liveCharStampHi: .fill 16, >liveCharStampAddresses.get(i)
liveCharVisited: .byte 0,0
liveCharOldLo: .fill 2 * BALL_COUNT, 0
liveCharOldEraseHi: .fill 2 * BALL_COUNT, 0
liveCharOldEraseLo: .fill 2 * BALL_COUNT, 0

.align $100
liveCharGlyphLo: .fill 256, <(i * 8)

.var liveCharBlendAddresses = List()
.var liveCharBlendAddress = LIVE_CHAR_BLEND_CODE
.for (var glyph = 0; glyph < FIXED_CHARS; glyph++) {
    .eval liveCharBlendAddresses.add(liveCharBlendAddress)
    .for (var row = 0; row < 8; row++) {
        .var byte = font.get(glyph * 8 + row) & $ff
        .var mask = liveCharKeepMask(byte)
        .eval liveCharBlendAddress += 6 + (mask != 0 && mask != $ff ? 4 : 0)
    }
    .eval liveCharBlendAddress++
}
liveCharBlendLo: .fill FIXED_CHARS, <liveCharBlendAddresses.get(i)
liveCharBlendHi: .fill FIXED_CHARS, >liveCharBlendAddresses.get(i)

// Emit once at $4000. Only the fixed front glyph is known here.
.macro emitCharacterBlendRoutines() {
    .for (var glyph = 0; glyph < FIXED_CHARS; glyph++) {
        .assert "Live blend routine address", *, liveCharBlendAddresses.get(glyph)
        .for (var row = 0; row < 8; row++) {
            .var byte = font.get(glyph * 8 + row) & $ff
            .var mask = liveCharKeepMask(byte)
            ldy #row
            .if (mask == 0) {
                lda #byte
            } else {
                lda (liveCharUnder),y
                .if (mask != $ff) {
                    and #mask
                    ora #byte
                }
            }
            sta (liveCharOutput),y
        }
        rts
    }
    .assert "Live blend runtime ends below I/O", * <= $d000, true
}


// Each copy has the same layout and a different absolute screen page.
.macro emitCharacterEraseRoutines() {
    .for (var page = 0; page < 8; page++) {
        .align $100
        .assert "Live erase page address", *, LIVE_CHAR_ERASE_CODE + page * $100
        .for (var index = 0; index < liveCharEraseSegments.size(); index++) {
            .assert "Live erase routine offset", <*, liveCharEraseUniqueOffsets.get(index)
            .var mask = liveCharEraseSegments.get(index)
            .for (var row = 0; row < LIVE_CHAR_TILE_SIZE; row++) {
                .for (var col = 0; col < LIVE_CHAR_TILE_SIZE; col++) {
                    .if ((mask & (1 << (row * LIVE_CHAR_TILE_SIZE + col))) != 0) {
                        sta SCREEN_A + page * $100 + row * LIVE_CHAR_SCREEN_WIDTH + col,y
                    }
                }
            }
            .if (liveCharEraseTails.get(index)) {
                jmp liveCharEraseContinue
            }
        }
    }
}

// Index by raster Y directly when selecting the tile phase and screen row.
.macro emitCharacterPositionTables() {
    .errorif * != LIVE_CHAR_POSITION_DATA, "Static character position tables start at the wrong address"
    .fill 256, (i & 6) * 2
    .fill 256, <((i >> 3) * LIVE_CHAR_SCREEN_WIDTH)
    .fill 256, >((i >> 3) * LIVE_CHAR_SCREEN_WIDTH)
    // These two pages already include the respective font bank's high byte.
    .fill 256, >(CHARSET + i * 8)
    .fill 256, >(CHARSET_B + i * 8)
}
