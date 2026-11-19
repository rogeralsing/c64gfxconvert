// X holds bit 0 for leftwards, bit 1 for upwards, and bit 2 for a Y-major line.
.macro SetupHoleLine() {
    ldx #0
    lda lx1
    sec
    sbc lx0
    bcs !dx+
    eor #$ff
    adc #1
    inx
!dx:
    sta cwMajorDelta
    lda ly1
    sec
    sbc ly0
    bcs !dy+
    eor #$ff
    adc #1
    inx
    inx
!dy:
    sta cwMinorDelta
    cmp cwMajorDelta
    bcc !axes+
    beq !axes+
    ldy cwMajorDelta
    sty cwMinorDelta
    sta cwMajorDelta
    txa
    ora #4
    tax
!axes:
    stx cwOrient
    lda holeMajorLo,x
    sta cwMajorStep
    lda holeMajorHi,x
    sta cwMajorStep+1
    lda holeMinorLo,x
    sta cwMinorStep
    lda holeMinorHi,x
    sta cwMinorStep+1
    lda holeBothLo,x
    sta cwBothStep
    lda holeBothHi,x
    sta cwBothStep+1

    lda lx0
    eor holeFlipX,x
    and #3
    tay
    lda ly0
    eor holeFlipY,x
    and #3
    cpx #4
    bcs !yMajor+
    sty cwMajorLocal
    sta cwMinorLocal
    bcc !locals+
!yMajor:
    sty cwMinorLocal
    sta cwMajorLocal
!locals:
    ldy ly0
    ldx lx0
    lda holeColumn,x
    clc
    adc holeRowLo,y
    sta scrLo
    lda holeRowHi,y
    adc baseHi
    sta scrHi
    lda baseLo
    beq !ready+
    clc
    adc scrLo
    sta scrLo
    bcc !ready+
    inc scrHi
!ready:
}

*=$0f40 "Line orientation and screen addresses"
.function ScreenMajor(o) {
    .if ((o & 4) == 0) { .return (o & 1) == 0 ? 1 : -1 }
    .return (o & 2) == 0 ? 40 : -40
}
.function ScreenMinor(o) {
    .if ((o & 4) == 0) { .return (o & 2) == 0 ? 40 : -40 }
    .return (o & 1) == 0 ? 1 : -1
}
holeMajorLo: .fill 8, <ScreenMajor(i)
holeMajorHi: .fill 8, >ScreenMajor(i)
holeMinorLo: .fill 8, <ScreenMinor(i)
holeMinorHi: .fill 8, >ScreenMinor(i)
holeBothLo:  .fill 8, <(ScreenMajor(i) + ScreenMinor(i))
holeBothHi:  .fill 8, >(ScreenMajor(i) + ScreenMinor(i))
holeFlipX:   .fill 8, (i & 1) == 0 ? 0 : 3
holeFlipY:   .fill 8, (i & 2) == 0 ? 0 : 3
holeColumn:  .fill 160, floor(i/4)
holeRowLo:   .fill 100, <(40 * floor(i/4))
holeRowHi:   .fill 100, >(40 * floor(i/4))
.assert "Line setup fits below the mesh code", * <= $1200, true
