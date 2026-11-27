.label motionX1 = $42
.label motionX2 = $44
.label motionY1 = $46
.label motionY2 = $48

initMotion:
    cld
    lda #0
    sta motionX1
    sta motionX2
    sta motionY1
    sta motionY2
    lda #>motionSine
    sta motionX1 + 1
    sta motionX2 + 1
    sta motionY1 + 1
    sta motionY2 + 1
    rts

advanceMotion:
    // Advance the low bytes by the four wave strides modulo 256.
    inc motionX1
    lda motionX2
    sec
    sbc #2
    sta motionX2
    lda motionY1
    clc
    adc #3
    sta motionY1
    lda motionY2
    sec
    sbc #4
    sta motionY2
    rts

// X selects the source ordinal and is preserved. Return wide X in A and raster Y in Y.
locateBall:
    ldy motionOffsetX1,x
    lda (motionX1),y
    ldy motionOffsetX2,x
    clc
    adc (motionX2),y
    tay
    lda motionQuantX,y
    sta ballX

    ldy motionOffsetY1,x
    lda (motionY1),y
    ldy motionOffsetY2,x
    clc
    adc (motionY2),y
    tay
    lda motionQuantY,y
    tay
    lda ballX
    rts

.align $100
.function motionSource(index) {
    .if (index < BALL_COUNT) { .return sourceData.get(index) }
    .return spriteSourceData.get(index - BALL_COUNT)
}
motionOffsetX1: .fill TOTAL_BALL_COUNT, (3 * motionSource(i)) & $ff
motionOffsetX2: .fill TOTAL_BALL_COUNT, (47 + 5 * motionSource(i)) & $ff
motionOffsetY1: .fill TOTAL_BALL_COUNT, (83 + 2 * motionSource(i)) & $ff
motionOffsetY2: .fill TOTAL_BALL_COUNT, (167 + 7 * motionSource(i)) & $ff

.align $100
motionQuantX: .fill 256, 4 + floor((144 * i + 127) / 254)
motionQuantY: .fill 256, 2 * (8 + floor((76 * i + 127) / 254))

.var motionSineData = LoadBinary(assets + "/sine.bin")
    .assert "Motion sine table has 256 entries", motionSineData.getSize(), 256
// Repeating the sine page lets indexed loads wrap without modifying any table.
motionSine: .fill 512, motionSineData.get(i & $ff) & $ff
