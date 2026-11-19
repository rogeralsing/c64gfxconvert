// Rotate the cube before projecting. Two X/Z pairs cover the four possible
// yaw results. Their two Y signs share pitch and roll products.
.macro CacheCubeTrig(phase, sine, cosine) {
    lda phase
    jsr loadSin
    lda m_b
    sta sine
    lda m_b+1
    sta sine+1
    lda phase
    clc
    adc #64
    jsr loadSin
    lda m_b
    sta cosine
    lda m_b+1
    sta cosine+1
}

.macro GroupedMultiply(lhs, rhs) {
    lda lhs
    sta m_a
    lda lhs+1
    sta m_a+1
    lda rhs
    sta m_b
    lda rhs+1
    sta m_b+1
    jsr mul16s
}

.macro Store24(source, target) {
    lda source
    sta target
    lda source+1
    sta target+1
    lda source+2
    sta target+2
}

.macro Negate24(value) {
    sec
    lda #0
    sbc value
    sta value
    lda #0
    sbc value+1
    sta value+1
    lda #0
    sbc value+2
    sta value+2
}

.macro AddSignedWord(value, rhs) {
    ldy #0
    lda rhs+1
    bpl !positive+
    dey
!positive:
    clc
    lda value
    adc rhs
    sta value
    lda value+1
    adc rhs+1
    sta value+1
    tya
    adc value+2
    sta value+2
}

.macro SubtractSignedWord(value, rhs) {
    ldy #0
    lda rhs+1
    bpl !positive+
    dey
!positive:
    sec
    lda value
    sbc rhs
    sta value
    lda value+1
    sbc rhs+1
    sta value+1
    lda value+2
    sty tmp
    sbc tmp
    sta value+2
}

.macro StoreFlooredSum(lhs, rhs, dest) {
    clc
    lda lhs
    adc rhs
    lda lhs+1
    adc rhs+1
    sta dest,x
    lda lhs+2
    adc rhs+2
    sta dest+1,x
}

.macro StoreFlooredDifference(lhs, rhs, dest) {
    sec
    lda lhs
    sbc rhs
    lda lhs+1
    sbc rhs+1
    sta dest,x
    lda lhs+2
    sbc rhs+2
    sta dest+1,x
}

.assert "Clipping code must end before grouped rotation", clipLineEnd <= $7800, true
*=$7800 "Grouped cube rotation"
groupedRotate:
    CacheCubeTrig(phYaw, groupedSinYaw, groupedCosYaw)
    CacheCubeTrig(phPit, groupedSinPitch, groupedCosPitch)
    CacheCubeTrig(phRol, groupedSinRoll, groupedCosRoll)

    // The cube's original X and Z coordinates are +1 or -1 in 8.8.
    clc
    lda groupedCosYaw
    adc groupedSinYaw
    sta groupedYawPlus
    lda groupedCosYaw+1
    adc groupedSinYaw+1
    sta groupedYawPlus+1
    sec
    lda groupedCosYaw
    sbc groupedSinYaw
    sta groupedYawMinus
    lda groupedCosYaw+1
    sbc groupedSinYaw+1
    sta groupedYawMinus+1

    GroupedMultiply(groupedCosPitch, groupedSinRoll)
    Store24(prod, groupedRollSinY)
    GroupedMultiply(groupedCosPitch, groupedCosRoll)
    Store24(prod, groupedRollCosY)
    lda #0
    sta groupedPair

groupedNextRepresentative:
    lda groupedPair
    bne !positiveZ+
    // Representative (x=+1,z=-1): x1=cy-sy, z1=-(cy+sy).
    lda groupedYawMinus
    sta rx1
    lda groupedYawMinus+1
    sta rx1+1
    sec
    lda #0
    sbc groupedYawPlus
    sta rz1
    lda #0
    sbc groupedYawPlus+1
    sta rz1+1
    jmp !pitch+
!positiveZ:
    // Representative (x=+1,z=+1): x1=cy+sy, z1=cy-sy.
    lda groupedYawPlus
    sta rx1
    lda groupedYawPlus+1
    sta rx1+1
    lda groupedYawMinus
    sta rz1
    lda groupedYawMinus+1
    sta rz1+1

!pitch:
    // Pitch bases exclude the original Y term. Keep the residues to
    // recover floor(-p/256) from floor(p/256) for the opposite X/Z pair.
    GroupedMultiply(rz1, groupedSinPitch)
    lda prod
    sta groupedYFraction
    sec
    lda #0
    sbc prod
    lda #0
    sbc prod+1
    sta ry1
    lda #0
    sbc prod+2
    sta ry1+1
    GroupedMultiply(rz1, groupedCosPitch)
    lda prod
    sta groupedZFraction
    lda prod+1
    sta rz2
    lda prod+2
    sta rz2+1

    GroupedMultiply(rx1, groupedCosRoll)
    jsr prodToSm
    GroupedMultiply(ry1, groupedSinRoll)
    jsr prodSubSm
    Store24(sm, groupedXBase)
    GroupedMultiply(rx1, groupedSinRoll)
    jsr prodToSm
    GroupedMultiply(ry1, groupedCosRoll)
    jsr prodAddSm
    Store24(sm, groupedYBase)
    jsr groupedStorePair

    // Opposite X/Z negates yaw exactly. Integer pitch then obeys
    // floor(-p/256) = -floor(p/256) - (p has a nonzero low byte).
    Negate24(groupedXBase)
    Negate24(groupedYBase)
    lda groupedYFraction
    beq !zBase+
    AddSignedWord(groupedXBase, groupedSinRoll)
    SubtractSignedWord(groupedYBase, groupedCosRoll)
!zBase:
    sec
    lda #0
    sbc rz2
    sta rz2
    lda #0
    sbc rz2+1
    sta rz2+1
    lda groupedZFraction
    beq !opposite+
    lda rz2
    bne !decrement+
    dec rz2+1
!decrement:
    dec rz2
!opposite:
    jsr groupedStorePair
    lda groupedPair
    cmp #4
    beq !done+
    jmp groupedNextRepresentative
!done:
    rts

groupedStorePair:
    ldy groupedPair
    ldx groupedNegativeY,y
    StoreFlooredSum(groupedXBase, groupedRollSinY, groupedVertices)
    StoreFlooredDifference(groupedYBase, groupedRollCosY, groupedVertices+2)
    sec
    lda rz2
    sbc groupedSinPitch
    sta groupedVertices+4,x
    lda rz2+1
    sbc groupedSinPitch+1
    sta groupedVertices+5,x

    ldx groupedPositiveY,y
    StoreFlooredDifference(groupedXBase, groupedRollSinY, groupedVertices)
    StoreFlooredSum(groupedYBase, groupedRollCosY, groupedVertices+2)
    clc
    lda rz2
    adc groupedSinPitch
    sta groupedVertices+4,x
    lda rz2+1
    adc groupedSinPitch+1
    sta groupedVertices+5,x
    inc groupedPair
    rts

groupedNegativeY:
    .byte 1*6, 4*6, 5*6, 0*6
groupedPositiveY:
    .byte 2*6, 7*6, 6*6, 3*6
// Private workspace for the rotation and projection stages.
groupedSinYaw:    .word 0
groupedCosYaw:    .word 0
groupedSinPitch:  .word 0
groupedCosPitch:  .word 0
groupedSinRoll:   .word 0
groupedCosRoll:   .word 0
groupedYawPlus:   .word 0
groupedYawMinus:  .word 0
groupedRollSinY:  .fill 3, 0 // cos(pitch) * sin(roll), signed 24-bit
groupedRollCosY:  .fill 3, 0 // cos(pitch) * cos(roll), signed 24-bit
groupedXBase:     .fill 3, 0 // roll before applying the original Y sign
groupedYBase:     .fill 3, 0
groupedYFraction: .byte 0
groupedZFraction: .byte 0
groupedPair:      .byte 0
groupedVertices:  .fill 8 * 6, 0 // signed 8.8 x, y, z in vertex order

groupedRotationEnd:
.assert "Grouped rotation must end before reciprocal data", groupedRotationEnd <= $8000, true
