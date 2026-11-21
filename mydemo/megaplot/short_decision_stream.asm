// Four pages describe the first 32 minor decisions for every Q8 rate.
// Align their packed bits at the head and then draw low and high nibbles.
.label cwShortBits = cwAdvanceLo
.label cwShortNibble = cwPhase
.label cwShortByte = cwThreshold
.label cwShortLocal = cwThreshold+1

.macro StampShortPair(full) {
    .if (full) {
        // The low nibble is the step pattern. The next two bits select the
        // minor start coordinate. Both glyph banks accept this key directly.
        ora cwShortLocal
        sta cwShortNibble
    } else {
        lda cwShortNibble
        and #7
        ldy cwMinorLocal
        ora charMinorIndex,y
        ora cwPairOffset
    }
    tay
    .if (!full) {
        lda (cwSecondLayout),y
        sta cwSecond
    }
    lda (cwLayout),y
    tax
    StampFirstGlyph()
    .if (full) {
        ldy cwShortNibble
        lda (cwSecondLayout),y
        beq !done+
        tax
    } else {
        lda cwSecond
        beq !done+
    }
    lda scrLo
    clc
    adc cwMinorStep
    sta jptrLo
    lda scrHi
    adc cwMinorStep+1
    sta jptrHi
    .if (full) { txa } else { lda cwSecond }
    jsr charStamp
!done:
}

.macro AdvanceShortCell(full) {
    .if (full) {
        ldx cwShortNibble
        lda shortFullNext,x
        lsr
        sta cwShortLocal
        bcc !majorOnly+
    } else {
        tax
        lda shortDecisionCount,x
        clc
        adc cwMinorLocal
        cmp #4
        bcc !majorOnly+
        and #3
        sta cwMinorLocal
    }
    lda scrLo
    clc
    adc cwBothStep
    sta scrLo
    lda scrHi
    adc cwBothStep+1
    sta scrHi
    jmp !advanced+
!majorOnly:
    .if (!full) { sta cwMinorLocal }
    lda scrLo
    adc cwMajorStep
    sta scrLo
    lda scrHi
    adc cwMajorStep+1
    sta scrHi
!advanced:
}

drawShortStream:
    ldx cwSlope
    lda shortDecisionBits,x
    sta cwShortBits
    lda shortDecisionBits+$100,x
    sta cwShortBits+1
    lda shortDecisionBits+$200,x
    sta cwShortBits+2
    lda shortDecisionBits+$300,x
    sta cwShortBits+3
    lda #0
    sta cwShortByte
    lda cwMajorLocal
    beq shortStreamInitLocal
    lda #4
    sec
    sbc cwMajorLocal
    cmp cwRemain
    bcc !count+
    lda cwRemain
!count:
    sta cwCount
    lda cwShortBits
    and #15
    sta cwShortNibble
    jsr shortStreamStampPartial
    lda cwRemain
    sec
    sbc cwCount
    bne !continue+
    rts
!continue:
    sta cwRemain
    ldx cwCount
    lda shortDecisionMask,x
    and cwShortNibble
    AdvanceShortCell(false)
    ldx cwCount
!align:
    lsr cwShortBits+3
    ror cwShortBits+2
    ror cwShortBits+1
    ror cwShortBits
    dex
    bne !align-
    stx cwMajorLocal
shortStreamInitLocal:
    ldx cwMinorLocal
    lda charMinorFullIndex,x
    sta cwShortLocal
    // Keep the tail count separate from the number of complete blocks.
    lda cwRemain
    tay
    and #3
    sta cwCount
    tya
    lsr
    lsr
    sta cwRemain
    bne shortStreamFullLow
    jmp shortStreamTailLow

// Up to seven complete groups fit in a short line. Each lane reads a
// known nibble from the aligned decision word.
.macro ShortFullFinish(block) {
    lda #floor((block+1)/2)
    .if ((block & 1) == 0) {
        jmp shortStreamFinishHigh
    } else {
        jmp shortStreamFinishLow
    }
}

.macro ShortFullBlock(block) {
    lda cwShortBits + floor(block/2)
    .if ((block & 1) == 0) {
        and #15
    } else {
        lsr
        lsr
        lsr
        lsr
    }
    StampShortPair(true)
    .if (block < 6) {
        dec cwRemain
        bne !continue+
        ShortFullFinish(block)
    !continue:
        AdvanceShortCell(true)
    } else {
        ShortFullFinish(block)
    }
}

shortStreamFullLow:
    .for (var block=0; block<7; block++) {
        ShortFullBlock(block)
    }

shortStreamFinishLow:
    sta cwShortByte
    lda cwCount
    beq shortStreamDone
    AdvanceShortCell(true)
    jmp shortStreamTailLow
shortStreamFinishHigh:
    sta cwShortByte
    lda cwCount
    beq shortStreamDone
    AdvanceShortCell(true)
    jmp shortStreamTailHigh
shortStreamDone:
    rts

shortStreamTailLow:
    ldx cwShortByte
    lda cwShortBits,x
    and #15
    jmp shortStreamTailReady
shortStreamTailHigh:
    ldx cwShortByte
    lda cwShortBits,x
    lsr
    lsr
    lsr
    lsr
shortStreamTailReady:
    sta cwShortNibble
    lda cwShortLocal
    lsr
    lsr
    lsr
    lsr
    sta cwMinorLocal
shortStreamStampPartial:
    lda cwCount
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
    StampShortPair(false)
    rts
!dot:
    ldx cwMajorLocal
    lda packedDotOffsets,x
    ora cwMinorLocal
    tay
    lda (cwLayout),y
    tax
    StampFirstGlyph()
    rts

shortDecisionCount:
    .byte 0,1,1,2,1,2,2,3,1,2,2,3,2,3,3,4
shortDecisionMask:
    .byte 0,1,3,7

// Bit zero advances the minor cell. Bits 5 and 6 become the next key.
shortFullNext:
    .byte 0,32,32,64,32,64,64,96,32,64,64,96,64,96,96,1
    .byte 32,64,64,96,64,96,96,1,64,96,96,1,96,1,1,33
    .byte 64,96,96,1,96,1,1,33,96,1,1,33,1,33,33,65
    .byte 96,1,1,33,1,33,33,65,1,33,33,65,33,65,65,97
