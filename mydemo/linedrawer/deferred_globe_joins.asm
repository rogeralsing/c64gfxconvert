// Each collision cell owns its patch code. Two reverse-map bytes hold its
// union until the back charset is filled before the border flip.
.function deferredExpand(n) {
    .return ((n&1)*192) | ((n&2)*24) | ((n&4)*3) | ((n&8) != 0 ? 3 : 0)
}

*=$9e00 "Expanded mask rows for deferred patches"
deferredExpandedLow: .fill 256, deferredExpand(i&15)
deferredExpandedHigh: .fill 256, deferredExpand(i>>4)

*=$a000 "Deferred glyph merges and flush"
deferredMerge:
    tay
    ldx jcode
    lda REVLO,y
    ora REVLO,x
    sta patLo
    lda REVHI,y
    ora REVHI,x
    cpy #201
    bcs !update+
    sta patHi
    cmp REVHI,y
    bne !incoming+
    lda patLo
    cmp REVLO,y
    beq !same+
!incoming:
    lda patHi
    cmp REVHI,x
    bne !allocate+
    lda patLo
    cmp REVLO,x
    beq !storeIncoming+
!allocate:
    ldx deferredNext
    beq !overflow+
    inc deferredNext
    lda patLo
    sta REVLO,x
    lda patHi
    sta REVHI,x
!storeIncoming:
    txa
    ldy #0
    sta (jptrLo),y
!same:
    rts
!update:
    sta REVHI,y
    lda patLo
    sta REVLO,y
    rts
!overflow:
    // Redraw this rare frame via the normal shared allocator.
    lda #1
    sta deferredOverflow
    rts

deferredFlush:
    lda deferredNext
    sec
    sbc #201
    sta JCOUNT
    bne !hasPatches+
    rts
!hasPatches:
    lda drawCharsetHi
    clc
    adc #6
    sta deferredRow0+2
    sta deferredRow1+2
    sta deferredRow2+2
    sta deferredRow3+2
    sta deferredRow4+2
    sta deferredRow5+2
    sta deferredRow6+2
    sta deferredRow7+2
    ldx #201
    ldy #<(201*8)
deferredFlushLoop:
    stx deferredFlushCode
    lda REVLO,x
    tax
    lda deferredExpandedLow,x
deferredRow0: sta $ff00,y
deferredRow1: sta $ff01,y
    lda deferredExpandedHigh,x
deferredRow2: sta $ff02,y
deferredRow3: sta $ff03,y
    ldx deferredFlushCode
    lda REVHI,x
    tax
    lda deferredExpandedLow,x
deferredRow4: sta $ff04,y
deferredRow5: sta $ff05,y
    lda deferredExpandedHigh,x
deferredRow6: sta $ff06,y
deferredRow7: sta $ff07,y
    ldx deferredFlushCode
    inx
    cpx deferredNext
    beq !done+
    tya
    clc
    adc #8
    tay
    bne deferredFlushLoop
    inc deferredRow0+2
    inc deferredRow1+2
    inc deferredRow2+2
    inc deferredRow3+2
    inc deferredRow4+2
    inc deferredRow5+2
    inc deferredRow6+2
    inc deferredRow7+2
    jmp deferredFlushLoop
!done:
    rts

.assert "Deferred join code fits before reverse masks", * <= REVLO, true
