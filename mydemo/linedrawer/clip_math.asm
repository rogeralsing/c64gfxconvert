// Intersect a signed 16-bit segment with an axis-aligned viewport side.
// clipBound is between clipFromAxis (outside) and clipToAxis. clipLimit is
// the maximum valid coordinate on the other axis; its minimum is zero.
// Return C set and A rounded to nearest (ties toward higher coordinates)
// only if the exact intersection lies on the finite side. C clear rejects.
.label clipFromAxis  = $c0
.label clipToAxis    = $c2
.label clipFromOther = $c4
.label clipToOther   = $c6
.label clipBound     = $c8
.label clipLimit     = $c9
.label clipDistance  = $ca
.label clipDivisor   = $cc
.label clipMagnitude = $ce
.label clipProduct   = $d0    // four bytes; then quotient and remainder
.label clipOtherDown = $d4
.label clipRounded   = $d5

clipIntersection:
    // Axis-aligned lines need no multiply or divide.
    lda clipFromOther
    cmp clipToOther
    bne !sloped+
    lda clipFromOther+1
    cmp clipToOther+1
    bne !sloped+
    cmp #0
    bne !reject+
    lda clipFromOther
    cmp clipLimit
    bcc !accept+
    beq !accept+
!reject:
    clc
    rts
!accept:
    sec
    rts

!sloped:
    lda clipFromAxis+1
    bmi !increasing+
    bne !decreasing+
    lda clipFromAxis
    cmp clipBound
    bcc !increasing+
!decreasing:
    lda clipFromAxis
    sec
    sbc clipToAxis
    sta clipDivisor
    lda clipFromAxis+1
    sbc clipToAxis+1
    sta clipDivisor+1
    lda clipFromAxis
    sec
    sbc clipBound
    sta clipDistance
    lda clipFromAxis+1
    sbc #0
    sta clipDistance+1
    jmp !otherDelta+
!increasing:
    lda clipToAxis
    sec
    sbc clipFromAxis
    sta clipDivisor
    lda clipToAxis+1
    sbc clipFromAxis+1
    sta clipDivisor+1
    lda clipBound
    sec
    sbc clipFromAxis
    sta clipDistance
    lda #0
    sbc clipFromAxis+1
    sta clipDistance+1

!otherDelta:
    lda #0
    sta clipOtherDown
    lda clipToOther
    sec
    sbc clipFromOther
    sta clipMagnitude
    lda clipToOther+1
    sbc clipFromOther+1
    sta clipMagnitude+1
    // N xor V orders the signed endpoints even when the difference wraps.
    bvc !direction+
    eor #$80
!direction:
    bpl !unsigned+
    dec clipOtherDown
    lda #0
    sec
    sbc clipMagnitude
    sta clipMagnitude
    lda #0
    sbc clipMagnitude+1
    sta clipMagnitude+1

!unsigned:
    // Unsigned distance * magnitude fits 32 bits for all int16 endpoints.
    lda #0
    sta clipProduct
    sta clipProduct+1
    sta clipProduct+2
    sta clipProduct+3
    ldx #16
!multiply:
    lsr clipDistance+1
    ror clipDistance
    bcc !shiftProduct+
    clc
    lda clipProduct+2
    adc clipMagnitude
    sta clipProduct+2
    lda clipProduct+3
    adc clipMagnitude+1
    sta clipProduct+3
!shiftProduct:
    ror clipProduct+3
    ror clipProduct+2
    ror clipProduct+1
    ror clipProduct
    dex
    bne !multiply-

    // Distance <= divisor, so the quotient fits 16 bits. The product's
    // high word is already less than divisor and seeds the remainder.
    ldx #16
!divide:
    asl clipProduct
    rol clipProduct+1
    rol clipProduct+2
    rol clipProduct+3
    bcs !subtract+
    lda clipProduct+3
    cmp clipDivisor+1
    bcc !nextBit+
    bne !subtract+
    lda clipProduct+2
    cmp clipDivisor
    bcc !nextBit+
!subtract:
    lda clipProduct+2
    sec
    sbc clipDivisor
    sta clipProduct+2
    lda clipProduct+3
    sbc clipDivisor+1
    sta clipProduct+3
    inc clipProduct
!nextBit:
    dex
    bne !divide-

    // Translate the quotient back to a coordinate. The remaining fraction
    // lies in the direction of motion, which matters at either bound.
    lda clipOtherDown
    bmi !moveDown+
    lda clipFromOther
    clc
    adc clipProduct
    sta clipRounded
    lda clipFromOther+1
    adc clipProduct+1
    jmp !check+
!moveDown:
    lda clipFromOther
    sec
    sbc clipProduct
    sta clipRounded
    lda clipFromOther+1
    sbc clipProduct+1
!check:
    bne !miss+
    lda clipRounded
    cmp clipLimit
    bcc !checkFraction+
    bne !miss+
!checkFraction:
    lda clipProduct+2
    ora clipProduct+3
    beq !return+
    lda clipOtherDown
    bmi !checkLower+
    lda clipRounded
    cmp clipLimit
    beq !miss+
    jmp !round+
!checkLower:
    lda clipRounded
    beq !miss+

!round:
    asl clipProduct+2
    rol clipProduct+3
    bcs !overHalf+
    lda clipProduct+3
    cmp clipDivisor+1
    bcc !return+
    bne !overHalf+
    lda clipProduct+2
    cmp clipDivisor
    bcc !return+
    bne !overHalf+
    lda clipOtherDown
    bmi !return+             // ties round toward the higher coordinate
!overHalf:
    lda clipOtherDown
    bmi !roundDown+
    inc clipRounded
    jmp !return+
!roundDown:
    dec clipRounded
!return:
    lda clipRounded
    sec
    rts
!miss:
    clc
    rts
