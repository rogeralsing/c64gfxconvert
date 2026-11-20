// Walk one major-axis character column or row per iteration. Lookup tables
// contain all glyphs for as many as four samples, including partial ends.
.label cwMajorDelta=$87
.label cwMinorDelta=$88
.label cwRemain=$89
.label cwPhase=$8a
.label cwMajorLocal=$8b
.label cwMinorLocal=$8c
.label cwCount=$8d
.label cwOrient=$8e
.label cwSlope=$8f
.label cwAdvanceLo=$90     // four fractional steps, indexed by count - 1
.label cwAdvanceHi=$94     // four whole steps
.label cwThreshold=$98    // three phase thresholds
.label cwShapes=$9b       // four possible shapes across the thresholds
.label cwLayout=$9f       // glyph pair lookup page
.label cwTransform=$a1    // page of reflected/transposed glyph codes
.label cwSecond=$a3
.label cwMajorStep=$a4
.label cwMinorStep=$a6
// Scratch shared with the legacy line drawer, which never calls this walker.
.label cwSecondLayout=recLo
.label cwBothStep=colLo

*= $7000 "Character line walker"
drawCharLine:
.if (CROSSING_HOLES) {
    SetupHoleLine()
} else {
    lda #0
    sta cwOrient
    .if (!ONE_CHAR) {
        sta cwLayout
        sta cwSecondLayout
        sta cwTransform
    }
    lda lx1
    sec
    sbc lx0
    bcs !dx+
    eor #$ff
    clc
    adc #1
    inc cwOrient
!dx:
    sta cwMajorDelta
    lda ly1
    sec
    sbc ly0
    bcs !dy+
    eor #$ff
    clc
    adc #1
    ldx cwOrient
    inx
    inx
    stx cwOrient
!dy:
    sta cwMinorDelta
    cmp cwMajorDelta
    bcc !axes+
    beq !axes+
    ldx cwMajorDelta
    stx cwMinorDelta
    sta cwMajorDelta
    lda cwOrient
    ora #4
    sta cwOrient
!axes:
    lda lx0
    and #3
    sta cwMajorLocal
    lda ly0
    and #3
    sta cwMinorLocal
    lda cwOrient
    lsr
    bcc !xPositive+
    lda cwMajorLocal
    eor #3
    sta cwMajorLocal
    lda #$ff
    sta cwMajorStep
    sta cwMajorStep+1
    jmp !xDone+
!xPositive:
    lda #1
    sta cwMajorStep
    lda #0
    sta cwMajorStep+1
!xDone:
    lda cwOrient
    and #2
    beq !yPositive+
    lda cwMinorLocal
    eor #3
    sta cwMinorLocal
    lda #256-40
    sta cwMinorStep
    lda #$ff
    sta cwMinorStep+1
    jmp !yDone+
!yPositive:
    lda #40
    sta cwMinorStep
    lda #0
    sta cwMinorStep+1
!yDone:
    lda cwOrient
    and #4
    beq !oriented+
    ldx cwMajorLocal
    ldy cwMinorLocal
    sty cwMajorLocal
    stx cwMinorLocal
    ldx cwMajorStep
    ldy cwMinorStep
    sty cwMajorStep
    stx cwMinorStep
    ldx cwMajorStep+1
    ldy cwMinorStep+1
    sty cwMajorStep+1
    stx cwMinorStep+1
!oriented:
    // A diagonal cell transition uses a single combined address increment.
    clc
    lda cwMajorStep
    adc cwMinorStep
    sta cwBothStep
    lda cwMajorStep+1
    adc cwMinorStep+1
    sta cwBothStep+1
    .if (!ONE_CHAR) {
        lda cwOrient
        clc
        adc #>charTransform
        sta cwTransform+1
    }
    // Lookup the 40-byte row offset. Add the cell column before the
    // buffer base so both low-byte carries reach the screen high byte.
    lda ly0
    lsr
    lsr
    tax
    lda lx0
    lsr
    lsr
    clc
    adc charRowLo,x
    sta scrLo
    lda charRowHi,x
    adc baseHi
    sta scrHi
    lda scrLo
    clc
    adc baseLo
    sta scrLo
    bcc !screenReady+
    inc scrHi
!screenReady:
}
    lda cwMajorDelta
    clc
    adc #1
    sta cwRemain
    .if (!CROSSING_HOLES) {
        lda #128
        sta cwPhase
    }

    // Select a rounded Q8 slope once for the whole line. Exact diagonals
    // have slope 256 and use a constant shape. A dot uses slope zero.
    lda cwMajorDelta
    beq !flat+
    cmp cwMinorDelta
    .if (CROSSING_HOLES) {
        bne !ordinary+
        jmp drawDiagonalHoleGroups
    !ordinary:
    } else {
        beq !diagonal+
    }
    .if (ONE_CHAR || CROSSING_HOLES || GLOBE_SHORT_RATES) {
        .label ratePointer = (CROSSING_HOLES || GLOBE_SHORT_RATES) ? jptrLo : cwSecondLayout
        tax
        ldy cwMinorDelta
        beq !flat+
        cpx #SHORT_RATE_LIMIT+1
        bcs !longLine+
        lda shortRateRowLo,x
        sta ratePointer
        lda shortRateRowHi,x
        sta ratePointer+1
        lda (ratePointer),y
        sta cwSlope
        jmp !table+
    !longLine:
    }
    lda #0
    sta cwSlope
    lda cwMinorDelta
    ldx #8
!divide:
    asl
    bcs !subtract+
    cmp cwMajorDelta
    bcc !quotient+
!subtract:
    sbc cwMajorDelta
    sec
!quotient:
    rol cwSlope
    dex
    bne !divide-
    asl
    bcs !round+
    cmp cwMajorDelta
    bcc !table+
!round:
    inc cwSlope
    jmp !table+
!flat:
    lda #0
    sta cwSlope
!table:
    .if (CROSSING_HOLES) { jmp drawHoleGroups }
    .if (!ONE_CHAR) {
        ldx cwSlope
        lda charSlope,x
        sta cwThreshold
        lda charSlope+$100,x
        sta cwThreshold+1
        lda charSlope+$200,x
        sta cwThreshold+2
        lda charSlope+$300,x
        sta cwShapes
        lda charSlope+$400,x
        sta cwShapes+1
        lda charSlope+$500,x
        sta cwShapes+2
        lda charSlope+$600,x
        sta cwShapes+3
    }
    ldx #0
    ldy #0
    tya
!advance:
    clc
    adc cwSlope
    sta cwAdvanceLo,x
    bcc !whole+
    iny
!whole:
    sty cwAdvanceHi,x
    inx
    cpx #4
    bne !advance-
    jmp charWalkBlock

!diagonal:
    .if (!ONE_CHAR) {
        lda #57                   // displacements 1, 2 and 3 packed in two bits each
        sta cwShapes+3
        lda #0
        sta cwThreshold+1
        sta cwThreshold+2
    } else {
        lda #0
    }
    sta cwAdvanceLo
    sta cwAdvanceLo+1
    sta cwAdvanceLo+2
    sta cwAdvanceLo+3
    lda #1
    sta cwAdvanceHi
    lda #2
    sta cwAdvanceHi+1
    lda #3
    sta cwAdvanceHi+2
    lda #4
    sta cwAdvanceHi+3

// A block touches the adjacent cell exactly when its last sample crosses
// the minor-axis boundary. Minor displacement is monotonic within the block.
.macro StampOneCharBlock(full) {
    lda #ONE_CHAR_CODE
    ldy #0
    sta (scrLo),y
    .if (!full) {
        ldx cwCount
        cpx #2
        bcc !done+
    }
    lda cwPhase
    clc
    .if (full) {
        adc cwAdvanceLo+2
        lda cwMinorLocal
        adc cwAdvanceHi+2
    } else {
        adc cwAdvanceLo-2,x
        lda cwMinorLocal
        adc cwAdvanceHi-2,x
    }
    cmp #4
    bcc !done+
    lda scrLo
    clc
    adc cwMinorStep
    sta jptrLo
    lda scrHi
    adc cwMinorStep+1
    sta jptrHi
    lda #ONE_CHAR_CODE
    sta (jptrLo),y
!done:
}

// Keep the prebuilt glyph in a clean cell. Distinct stamps on the same
// cell mark it with a blank glyph until the next clear.
.macro StampWithCrossingHoles(screenPointer) {
    ldy #0
    // Clean builds dispatch to drawHoleGroups before this generic block.
    .if (CLEAN_JUNCTIONS) {
        txa
        ora (screenPointer),y
        sta (screenPointer),y
    } else {
        lda (screenPointer),y
        beq !empty+
        cmp #HOLE_CODE
        beq !done+
        stx jcode
        cmp jcode
        beq !done+
        lda #HOLE_CODE
        bne !write+
    !empty:
        txa
    !write:
        sta (screenPointer),y
    !done:
    }
}

// The middle of a line advances four samples per block. Its two glyph
// pages are constant, while clipped first and last blocks select their pages.
.macro StampWalkBlock(full) {
    // Pick one of at most four shapes using the phase at this block.
    lda cwPhase
    cmp cwThreshold+1
    bcc !lower+
    ldx #2
    cmp cwThreshold+2
    bcc !shape+
    inx
    jmp !shape+
!lower:
    ldx #0
    cmp cwThreshold
    bcc !shape+
    inx
!shape:
    ldy cwMinorLocal
    lda charMinorIndex,y
    ora cwShapes,x
    tay
    .if (full) {
        lda charSecond + 3 * 256,y
    } else {
        lda (cwSecondLayout),y
    }
    sta cwSecond
    .if (full) {
        lda charFirst + 3 * 256,y
    } else {
        lda (cwLayout),y
    }
    tay
    lda (cwTransform),y
    tax
    .if (COMPACT_JOINS) {
        lda scrLo
        sta jptrLo
        lda scrHi
        sta jptrHi
        jsr compactStamp
    } else {
        .if (CROSSING_HOLES) {
            StampWithCrossingHoles(scrLo)
        } else {
            ldy #0
            lda (scrLo),y
            beq !empty+
            jsr charComposeFirst
            jmp !firstStamped+
        !empty:
            txa
            sta (scrLo),y
        !firstStamped:
        }
    }
    lda cwSecond
    beq !stamped+
    lda scrLo
    clc
    adc cwMinorStep
    sta jptrLo
    lda scrHi
    adc cwMinorStep+1
    sta jptrHi
    lda cwSecond
    jsr charStamp
!stamped:
}

// Advance once to the next major-axis cell. The fractional carry adds one
// to the whole minor displacement.
.macro AdvanceWalkBlock(full) {
    .if (!full) {
        ldx cwCount
    }
    lda cwPhase
    clc
    .if (full) {
        adc cwAdvanceLo+3
    } else {
        adc cwAdvanceLo-1,x
    }
    sta cwPhase
    lda cwMinorLocal
    .if (full) {
        adc cwAdvanceHi+3
    } else {
        adc cwAdvanceHi-1,x
    }
    cmp #4
    bcc !majorOnly+
    and #3
    sta cwMinorLocal
    lda scrLo
    clc
    adc cwBothStep
    sta scrLo
    lda scrHi
    adc cwBothStep+1
    sta scrHi
    jmp !advanced+
!majorOnly:
    sta cwMinorLocal
    lda scrLo
    adc cwMajorStep
    sta scrLo
    lda scrHi
    adc cwMajorStep+1
    sta scrHi
!advanced:
}

charWalkBlock:
    lda cwMajorLocal
    bne !partial+
    lda cwRemain
    cmp #4
    .if (GLOBE_MOTIFS) {
        bcc !partial+
        jmp globeMotifsBegin
    } else .if (GLOBE_REPEAT) {
        bcc !partial+
        lda cwAdvanceLo+3
        bne charWalkFull
        jmp globeRepeatTry
    } else {
        bcs charWalkFull
    }
!partial:
    jmp charWalkPartial
charWalkFull:
    .if (ONE_CHAR) {
        StampOneCharBlock(true)
    } else {
        StampWalkBlock(true)
    }
    lda cwRemain
    sec
    sbc #4
    sta cwRemain
    beq charWalkDone
    AdvanceWalkBlock(true)
    lda cwRemain
    cmp #4
    bcc charWalkPartial
    jmp charWalkFull
charWalkDone:
    rts

charWalkPartial:
    lda #4
    sec
    sbc cwMajorLocal
    cmp cwRemain
    bcc !count+
    lda cwRemain
!count:
    sta cwCount
    .if (ONE_CHAR) {
        StampOneCharBlock(false)
    } else {
        lda cwMajorLocal
        asl
        asl
        clc
        adc cwCount
        adc #(>charFirst - 1)
        sta cwLayout+1
        adc #((>charSecond) - (>charFirst))
        sta cwSecondLayout+1
        StampWalkBlock(false)
    }
    lda cwRemain
    sec
    sbc cwCount
    sta cwRemain
    beq charWalkDone
    AdvanceWalkBlock(false)
    lda #0
    sta cwMajorLocal
    jmp charWalkBlock

// The common blank write uses the walk pointer directly. Prepare the joint
// pointer only when the primary cell already holds a different character.
charComposeFirst:
    stx jcode
    cmp jcode
    beq !same+
    lda scrLo
    sta jptrLo
    lda scrHi
    sta jptrHi
    jmp stampJoint
!same:
    rts

charStamp:
    tay
    lda (cwTransform),y
    .if (COMPACT_JOINS) {
        tax
        jmp compactStamp
    } else {
        .if (CROSSING_HOLES) {
            tax
            StampWithCrossingHoles(jptrLo)
            rts
        } else {
            sta jcode
            ldy #0
            lda (jptrLo),y
            beq !write+
            cmp jcode
            beq !done+
            jmp stampJoint
        !write:
            lda jcode
            sta (jptrLo),y
        !done:
            rts
        }
    }

charMinorIndex:
    .byte $00,$40,$80,$c0
charRowLo:
    .fill 25, <(i * 40)
charRowHi:
    .fill 25, >(i * 40)

.assert "Character line walker fits before the clipper", * <= $7400, true

.if (CROSSING_HOLES) {
    *= $b400 "Decision-window character walker"
    .import source "hole_walk.asm"
    .assert "Window walker fits below the bit-reverse table", * <= $b600, true
}
