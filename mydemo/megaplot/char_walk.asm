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
.label cwPairOffset=$a1
.label cwSecond=$a3
.label cwMajorStep=$a4
.label cwMinorStep=$a6
// Two-byte scratch values for the second glyph table and diagonal screen step.
.label cwSecondLayout=$0e
.label cwBothStep=$20

*= $7000 "Character line walker"
drawCharLine:
    ldx #0
    stx cwLayout
    stx cwSecondLayout
    lda lx1
    sec
    sbc lx0
    bcs !positiveX+
    eor #$ff
    adc #1
    inx
!positiveX:
    sta cwMajorDelta
    lda ly1
    sec
    sbc ly0
    bcs !positiveY+
    eor #$ff
    adc #1
    inx
    inx
!positiveY:
    sta cwMinorDelta
    cmp cwMajorDelta
    bcc !ordered+
    beq !ordered+
    ldy cwMajorDelta
    sty cwMinorDelta
    sta cwMajorDelta
    txa
    ora #4
    tax
!ordered:
    stx cwOrient
    lda lx0
    and #3
    eor octFlipX,x
    tay
    lda ly0
    and #3
    eor octFlipY,x
    cpx #4
    bcc !xMajor+
    sta cwMajorLocal
    sty cwMinorLocal
    bcs !normalized+
!xMajor:
    sty cwMajorLocal
    sta cwMinorLocal
!normalized:
    lda octMajorLo,x
    sta cwMajorStep
    lda octMajorHi,x
    sta cwMajorStep+1
    lda octMinorLo,x
    sta cwMinorStep
    lda octMinorHi,x
    sta cwMinorStep+1
    // Combined major and minor screen steps are fixed for each octant.
    lda octBothLo,x
    sta cwBothStep
    lda octBothHi,x
    sta cwBothStep+1
    lda cwOrient
    clc
    adc #>packedFirst
    sta cwLayout+1
    adc #((>packedSecond) - (>packedFirst))
    sta cwSecondLayout+1
    // Both screen buffers start on a page boundary.
    ldx lx0
    ldy ly0
    lda waveStartColumn,x
    clc
    adc waveStartRowLo,y
    sta scrLo
    lda waveStartRowHi,y
    adc baseHi
    sta scrHi
    lda cwMajorDelta
    clc
    adc #1
    sta cwRemain
    lda #128
    sta cwPhase

    // Look up the rounded Q8 slope for the entire segment.
    ldx cwMajorDelta
    beq !flat+
    cpx cwMinorDelta
    beq !diagonal+
    lda slopeRowLo,x
    sta dstLo
    lda slopeRowHi,x
    sta dstHi
    ldy cwMinorDelta
    lda (dstLo),y
    jmp !table+
!flat:
    lda #0
!table:
    sta cwSlope
    ldx cwMajorDelta
    cpx #29
    bcs !generic+
    and #63
    beq !generic+
    jmp drawShortStream
!generic:
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
    // Derive the first two exact Q8 multiples from the indexed rate.
    stx cwAdvanceLo
    txa
    asl
    sta cwAdvanceLo+1
    lda #0
    sta cwAdvanceHi
    rol
    sta cwAdvanceHi+1
    // Add one rate to 2× for 3×, then double 2× for 4×.
    lda cwAdvanceLo+1
    clc
    adc cwSlope
    sta cwAdvanceLo+2
    lda cwAdvanceHi+1
    adc #0
    sta cwAdvanceHi+2
    lda cwAdvanceLo+1
    asl
    sta cwAdvanceLo+3
    lda cwAdvanceHi+1
    rol
    sta cwAdvanceHi+3
    jmp charWalkBlock

!diagonal:
    lda #7                        // three successive minor steps
    sta cwShapes+3
    lda #0
    sta cwThreshold+1
    sta cwThreshold+2
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

.macro StampFirstGlyph() {
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
    .if (full) {
        lda charMinorFullIndex,y
    } else {
        lda charMinorIndex,y
    }
    ora cwShapes,x
    .if (!full) { ora cwPairOffset }
    tay
    lda (cwSecondLayout),y
    sta cwSecond
    lda (cwLayout),y
    tax
    StampFirstGlyph()
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
    bcs charWalkFull
!partial:
    jmp charWalkPartial
charWalkFull:
    StampWalkBlock(true)
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
    cmp #1
    beq !dot+
    lda cwMajorLocal
    asl
    asl
    clc
    adc cwCount
    tax
    lda packedLayoutOffsets,x
    sta cwPairOffset
    StampWalkBlock(false)
    jmp !afterStamp+
!dot:
    ldx cwMajorLocal
    lda packedDotOffsets,x
    ora cwMinorLocal
    tay
    lda (cwLayout),y
    tax
    StampFirstGlyph()
!afterStamp:
    lda cwRemain
    sec
    sbc cwCount
    sta cwRemain
    bne !advance+
    rts
!advance:
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
    ldx scrLo
    stx jptrLo
    ldx scrHi
    stx jptrHi
    jmp sjCompose
!same:
    rts

charStamp:
    sta jcode
    ldy #0
    lda (jptrLo),y
    beq !write+
    cmp jcode
    beq !done+
    jmp sjCompose
!write:
    lda jcode
    sta (jptrLo),y
!done:
    rts

charMinorIndex:
    .byte 0,8,16,24
charMinorFullIndex:
    .byte 0,16,32,48
packedLayoutOffsets:
    .byte 0,0,64,96,0,0,128,160,0,0,192,0
packedDotOffsets:
    .byte 224,228,232,236
octFlipX:
    .byte 0,3,0,3,0,3,0,3
octFlipY:
    .byte 0,0,3,3,0,0,3,3
octMajorLo:
    .byte <1,<-1,<1,<-1,<40,<40,<-40,<-40
octMajorHi:
    .byte >1,>-1,>1,>-1,>40,>40,>-40,>-40
octMinorLo:
    .byte <40,<40,<-40,<-40,<1,<-1,<1,<-1
octMinorHi:
    .byte >40,>40,>-40,>-40,>1,>-1,>1,>-1

octBothLo:
    .byte <41,<39,<-39,<-41,<41,<39,<-39,<-41
octBothHi:
    .byte >41,>39,>-39,>-41,>41,>39,>-39,>-41

.assert "Walker fits before the glyph dictionary", * <= $7400, true
