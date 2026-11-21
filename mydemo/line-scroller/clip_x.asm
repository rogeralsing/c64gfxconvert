// Clip a glyph stroke at x=0 or x=159 before drawing it. Y is already
// within 0..99. The horizontal span is at most 64 logical pixels, so
// a stroke cannot cross both side edges.
.label scClipBoundary = jptrHi
.label scClipSpan = scrLo
.label scClipDistance = scrHi
.label scClipYDelta = patLo
.label scClipMagnitude = patHi

.macro AbsClipDifference() {
    bpl !positive+
    eor #$ff
    clc
    adc #1
!positive:
}

* = $3a00 "Scroller horizontal viewport clipping"
drawScrollerLine:
    lda scX0Hi
    ora scX1Hi
    bne scClipEdge
    lda lx0
    cmp #160
    bcs scClipEdge
    lda lx1
    cmp #160
    bcs scClipEdge
    jmp drawCharLine

scClipEdge:
    // X indexes the outside endpoint. Y will index the inside endpoint.
    ldx #0
    lda scX0Hi
    bmi scClipLeft
    bne scClipRight
    lda lx0
    cmp #160
    bcs scClipRight
    ldx #2
    lda scX1Hi
    bmi scClipLeft
scClipRight:
    lda #159
    bne scClipSelected
scClipLeft:
    lda #0
scClipSelected:
    sta scClipBoundary
    ldy #0
    cpx #0
    bne scClipCrossing       // Endpoint zero was already checked.
    lda scX1Hi
    bne scClipReject
    lda lx1
    cmp #160
    bcs scClipReject
    ldy #2
scClipCrossing:
    lda ly0,y
    sec
    sbc ly0,x
    beq scClipSetX
    sta scClipYDelta
    AbsClipDifference()
    sta scClipMagnitude

    lda lx0,y
    sec
    sbc lx0,x
    AbsClipDifference()
    sta scClipSpan
    lda scClipBoundary
    sec
    sbc lx0,x
    AbsClipDifference()
    sta scClipDistance
    jsr scClipRoundedOffset
    clc
    bit scClipYDelta
    bpl !addY+
    eor #$ff
    sec
!addY:
    adc ly0,x
    sta ly0,x

scClipSetX:
    lda scClipBoundary
    sta lx0,x
    lda #0
    cpx #0
    bne !end+
    sta scX0Hi
    jmp drawCharLine
!end:
    sta scX1Hi
    jmp drawCharLine
scClipReject:
    rts

// Return floor((distance * magnitude + span / 2) / span).
// The signed Y delta is reapplied by the caller, so halves round towards
// the inside endpoint in either direction.
scClipRoundedOffset:
    lda #0
    lsr scClipDistance
    .for (var bitNumber=0; bitNumber<8; bitNumber++) {
        bcc !shift+
        clc
        adc scClipMagnitude
    !shift:
        ror
        ror scClipDistance
    }
    // A and scClipDistance hold the two-byte product.
    tay
    lda scClipSpan
    lsr
    clc
    adc scClipDistance
    sta scClipDistance
    tya
    adc #0
    .for (var bitNumber=0; bitNumber<8; bitNumber++) {
        asl scClipDistance
        rol
        cmp scClipSpan
        bcc !next+
        sbc scClipSpan
        inc scClipDistance
    !next:
    }
    lda scClipDistance
    rts

.assert "Scroller clipping fits before the first glyph table", * <= $4000, true
