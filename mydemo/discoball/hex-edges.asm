// Fixed hexagon endpoints remove per-edge copies and coordinate swaps. Both
// directions retain the shared half-open X interval and exact crossing curves.
.macro OrderedHexEdge(startX, startY, endX, endY) {
    lda startX
    tax
    lda facePointerHigh
    sta spritePointer+1
    lda byteColumns,x
    clc
    adc facePointerLow
    clc
    adc startY
    sec
    sbc #20
    sta spritePointer
    bcs !pointerReady+
    dec spritePointer+1
!pointerReady:
    lda endX
    sec
    sbc startX
    tax
    lda endY
    sec
    sbc startY
    clc
    adc hexEdgeIndexBase,x
    tax
    lda hexEdgeCompactLow,x
    sta curveRead+1
    lda hexEdgeCompactHigh,x
    sta curveRead+2
    lda curveRead+1
    sec
    sbc startX
    sta curveRead+1
    bcs !curveReady+
    dec curveRead+2
!curveReady:
    ldx startX
!pixel:
curveRead:
    ldy $ffff,x
    lda bitMasks,x
    eor (spritePointer),y
    sta (spritePointer),y
    inx
    cpx endX
    beq !done+
    txa
    and #7
    bne !sameByte+
    lda spritePointer
    clc
    adc #21
    sta spritePointer
    bcc !sameByte+
    inc spritePointer+1
!sameByte:
    jmp !pixel-
!done:
    rts
}

.macro FixedHexEdge(first, second) {
    lda localX+first
    cmp localX+second
    bcc !forward+
    bne !reverse+
    rts
!forward:
    OrderedHexEdge(localX+first, localY+first, localX+second, localY+second)
!reverse:
    OrderedHexEdge(localX+second, localY+second, localX+first, localY+first)
}

drawHexEdge0: FixedHexEdge(0, 1)
drawHexEdge1: FixedHexEdge(1, 2)
drawHexEdge2: FixedHexEdge(2, 3)
drawHexEdge3: FixedHexEdge(3, 4)
drawHexEdge4: FixedHexEdge(4, 5)
drawHexEdge5: FixedHexEdge(5, 0)

// A pentagon closes at its fifth shared corner; no sixth corner is read.
drawPentEdge4: FixedHexEdge(4, 0)
