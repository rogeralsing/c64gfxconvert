.assert "Grouped rotation must end before projection", groupedRotationEnd <= $7c00, true
*=$7c00 "Exact high-word perspective product"

// A is a signed position in m_a, B is a nonnegative 16-bit reciprocal in
// m_b. Return (A*B+$8000)>>16 in prod+2:prod+3 and leave B available for Y.
// Split A into an unsigned low byte L and signed high byte H. The result
// is floor((high8(L*lo(B)) + L*hi(B) + 128 + H*B)/256).
projectReciprocalWord:
    lda m_a+1
    bmi !checkNegative+
    cmp #4
    bcc !small+
    jmp projectReciprocalGeneral
!checkNegative:
    cmp #$fc
    bcs !small+
    jmp projectReciprocalGeneral

!small:
    lda m_a
    ldx m_b
    jsr mul8Quarter
    clc
    adc #$80
    sta prod+1
    lda #0
    adc #0
    sta prod+2

    lda m_a
    ldx m_b+1
    jsr mul8Quarter
    tax
    clc
    lda qsProdLo
    adc prod+1
    sta prod+1
    txa
    adc prod+2
    sta prod+2
    lda #0
    adc #0
    sta prod+3

    ldx m_a+1
    beq !done+
    bmi !negative+
!add:
    clc
    lda prod+1
    adc m_b
    sta prod+1
    lda prod+2
    adc m_b+1
    sta prod+2
    lda prod+3
    adc #0
    sta prod+3
    dex
    bne !add-
    rts

!negative:
    txa
    eor #$ff
    clc
    adc #1
    tax
!subtract:
    sec
    lda prod+1
    sbc m_b
    sta prod+1
    lda prod+2
    sbc m_b+1
    sta prod+2
    lda prod+3
    sbc #0
    sta prod+3
    dex
    bne !subtract-
!done:
    rts

// Maintain the full signed input range if later scenes use wider positions.
// mul16s preserves the nonnegative m_b used here.
projectReciprocalGeneral:
    jsr mul16s
    clc
    lda prod+1
    adc #$80
    lda prod+2
    adc #0
    sta prod+2
    lda prod+3
    adc #0
    sta prod+3
    rts

projectReciprocalEnd:
.assert "Perspective product must end before reciprocal data", projectReciprocalEnd <= $8000, true
