// The stream starts at the line origin. Select column alignment and starting
// minor coordinate once. Every subsequent block can be decoded independently.
.label holeTrace = entLo
.label holeShiftPtr = glyLo
.label holeWindowIndex = cwPhase
.label holeShapeKey = cwShapes
.label holeFullCount = cwAdvanceLo
.label holeTail = cwAdvanceLo+1
.label holePrimaryY = cwAdvanceHi
.label holeSecondaryY = cwAdvanceHi+1

// Carry selects the combined major/minor address increment.
.macro AdvanceHolePointer() {
    lsr
    bcs !diagonal+
    lda scrLo
    adc cwMajorStep
    sta scrLo
    lda scrHi
    adc cwMajorStep+1
    sta scrHi
    jmp !done+
!diagonal:
    lda scrLo
    clc
    adc cwBothStep
    sta scrLo
    lda scrHi
    adc cwBothStep+1
    sta scrHi
!done:
}

drawHoleGroups:
    ldx cwSlope
    lda holeWindowLo,x
    ldy holeWindowHi,x
    jmp holeTraceSelected
drawDiagonalHoleGroups:
    lda #<(holeWindows + 256*40)
    ldy #>(holeWindows + 256*40)
holeTraceSelected:
    sta holeTrace
    sty holeTrace+1
    // The secondary address differs by one row or column. Bias the pointer
    // once so both cell offsets used by (scrLo),Y are nonnegative.
    ldx #0
    lda cwMinorStep+1
    beq !positive+
    lda scrLo
    clc
    adc cwMinorStep
    sta scrLo
    lda scrHi
    adc cwMinorStep+1
    sta scrHi
    lda #0
    sec
    sbc cwMinorStep
    sta holePrimaryY
    stx holeSecondaryY
    jmp !offsets+
!positive:
    stx holePrimaryY
    lda cwMinorStep
    sta holeSecondaryY
!offsets:
    stx holeWindowIndex
    ldy cwMinorLocal
    lda phaseBias,y
    sta holeShiftPtr
    lda #>phase0
    sta holeShiftPtr+1
    lda cwMajorLocal
    beq !fullGroups+
    lda #4
    sec
    sbc cwMajorLocal
    cmp cwRemain
    bcc !prefix+
    lda cwRemain
!prefix:
    sta cwCount
    jsr holeDirectPartial
    lda cwRemain
    sec
    sbc cwCount
    bne !more+
    rts
!more:
    sta cwRemain
    jsr holeAdvancePartial
    ldx cwCount
    lda phasePage,x
    sta holeShiftPtr+1
!fullGroups:
    lda cwRemain
    and #3
    sta holeTail
    lda cwRemain
    lsr
    lsr
    bne !full+
    jmp holeDrawTail
!full:
    // Enter the unrolled loop at the lane that leaves a multiple of four blocks.
    tax
    lda kernelLastLoop,x
    sta holeFullCount
    lda kernelLane,x
    ora cwOrient
    tax
    lda kernelStartLo,x
    sta cwLayout
    lda kernelStartHi,x
    sta cwLayout+1
    jmp (cwLayout)
holeDrawTail:
    lda holeTail
    beq !done+
    cmp #1
    bne !multi+
    ldy holeWindowIndex
    lda (holeTrace),y
    tay
    lda (holeShiftPtr),y
    tay
    lda holeNormalizedKey,y
    and #24
    ora cwOrient
    tax
    lda holeTailDot,x
    tax
    jmp holeOnlyFirst
!multi:
    sta cwCount
    lda #0
    sta cwMajorLocal
    jmp holeDirectPartial
!done:
    rts

holeDirectPartial:
    ldy holeWindowIndex
    lda (holeTrace),y
    tay
    lda (holeShiftPtr),y
    tay
    lda holeNormalizedKey,y
    sta holeShapeKey
    and #31
    tay
    ldx cwCount
    lda holeCountIndex,x
    ldx cwMajorLocal
    ora holeStartIndex,x
    ora cwOrient
    asl
    // Select a word in the page-aligned jump table by patching the operand low byte.
    sta holePartialDispatch+1
holePartialDispatch:
    jmp (holePartialJumps)

holeDirectPair:
    .if (CLEAN_JUNCTIONS) {
        cmp #0
        beq holeOnlyFirst
        sta jcode
        ldy holeSecondaryY
        lda (scrLo),y
        beq !empty+
        cmp jcode
        beq holeOnlyFirst
        stx slotLane
        .if (FIXED_JUNCTION_FONT) { sty coverOffset }
        tay
        ldx jcode
        jsr mergeJunction
        ldx slotLane
        ldy holeSecondaryY
        bpl !store+
!empty:
        lda jcode
!store:
        sta (scrLo),y
    } else {
        sta cwSecond
        ldy holePrimaryY
        lda (scrLo),y
        beq !empty+
        cmp #HOLE_CODE
        beq !second+
        stx jcode
        cmp jcode
        beq !second+
        lda #HOLE_CODE
        bne !write+
!empty:
        txa
!write:
        sta (scrLo),y
!second:
        ldx cwSecond
        beq !done+
        ldy holeSecondaryY
        lda (scrLo),y
        beq !empty+
        cmp #HOLE_CODE
        beq !done+
        cmp cwSecond
        beq !done+
        lda #HOLE_CODE
        bne !write+
!empty:
        txa
!write:
        sta (scrLo),y
!done:
        rts
    }
holeOnlyFirst:
    .if (CLEAN_JUNCTIONS) {
        ldy holePrimaryY
        lda (scrLo),y
        beq !empty+
        stx jcode
        cmp jcode
        beq !done+
        .if (FIXED_JUNCTION_FONT) { sty coverOffset }
        tay
        jsr mergeJunction
        ldy holePrimaryY
        bpl !store+
!empty:
        txa
!store:
        sta (scrLo),y
!done:
        rts
    } else {
        ldy holePrimaryY
        lda (scrLo),y
        bne !occupied+
        txa
        sta (scrLo),y
        rts
!occupied:
        cmp #HOLE_CODE
        beq !done+
        stx jcode
        cmp jcode
        beq !done+
        lda #HOLE_CODE
        sta (scrLo),y
!done:
        rts
    }

holeCountIndex: .byte 0, 0, 8, 16, 24
holeStartIndex: .byte 0, 32, 64, 96

holeAdvancePartial:
    lda cwCount
    sec
    sbc #1
    lsr
    ror
    ror
    ora holeShapeKey
    tax
    lda holeAdvance,x
    AdvanceHolePointer()
    rts
