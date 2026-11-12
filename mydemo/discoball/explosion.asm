// Detach the visible hexagons. Their local shapes keep rotating while their
// origins travel independently in screen space, with signed positions so no
// piece wraps around the display when it leaves an edge.
* = $c900 "Detached hexagon fragments"

beginExplosion:
    lda #0
    sta shapeMode
    sta explosionAge
    sta explosionDone
    sta explosionCount
    sta explosionScan
    sta explosionXHigh
    lda zoomScale
    sta explosionScale
    ldx zoomPhase
    sta zoomScaleTable,x
    jsr cullHexagons
    jsr selectLargestHexagons
    jsr projectSharedVertices
!face:
    ldx explosionScan
    lda faceDepths,x
    bpl !next+
    stx faceIndex
    jsr projectFace
    ldy explosionCount
    lda faceIndex
    sta explosionFaces,y
    lda minX
    asl
    clc
    adc #SCENE_X_BIAS
    sta explosionXLo,y
    lda minY
    asl
    clc
    adc #SCENE_Y_BIAS
    sta explosionYLo,y
    lda #0
    sta explosionXHi,y
    sta explosionYHi,y
    inc explosionCount
!next:
    inc explosionScan
    lda explosionScan
    cmp #20
    bne !face-
    // The normal renderer pays no per-face dispatch cost for the outro hook.
    lda #$4c
    sta facePosition
    lda #<explosionPositionStore
    sta facePosition+1
    lda #>explosionPositionStore
    sta facePosition+2
    rts

renderExplosion:
    lda #0
    sta explosionPiece
    sta explosionEnabled
    sta explosionXHigh
    jsr cullHexagons
    jsr projectSharedVertices
!piece:
    ldx explosionPiece
    lda explosionFaces,x
    sta faceIndex
    jsr explosionVisible
    bcc !hidden+
    ldx faceIndex
    lda faceDepths,x
    bmi !depth+
    eor #$ff
    clc
    adc #1
    bne !depth+
    lda #$ff
!depth:
    sta normalDepth
    jsr projectFace
    jsr drawFace
    jmp !next+
!hidden:
    lda usedSprites
    clc
    adc metadataBase
    tax
    lda faceIndex
    sta slotFace,x
    lda #0
    sta slotX,x
    sta slotY,x
    sta slotColor,x
    inc usedSprites
!next:
    inc explosionPiece
    lda explosionPiece
    cmp explosionCount
    bne !piece-
    ldx explosionCount
    lda explosionEnabled
    sta enableMasks,x
    rts

// Carry indicates intersection with the normal 320x200 display window.
explosionVisible:
    ldx explosionPiece
    lda explosionYHi,x
    bne !hidden+
    lda explosionYLo,x
    cmp #9
    bcc !hidden+
    cmp #250
    bcs !hidden+
    lda explosionXHi,x
    beq !visible+
    cmp #1
    beq !right+
    cmp #$ff
    bne !hidden+
    lda explosionXLo,x
    cmp #233
    bcc !hidden+
    bcs !visible+
!right:
    lda explosionXLo,x
    cmp #88
    bcs !hidden+
!visible:
    sec
    rts
!hidden:
    clc
    rts

// X is the destination metadata index from drawFace. PAL's X counter wraps
// at 504; negative coordinates must avoid the unreachable $1f8..$1ff range.
explosionPositionStore:
    ldy explosionPiece
    lda explosionXHi,y
    beq !lowOnly+
    cmp #$ff
    bne !positiveHigh+
    lda explosionXLo,y
    sec
    sbc #8
    sta slotX,x
    jmp !high+
!positiveHigh:
    lda explosionXLo,y
    sta slotX,x
!high:
    ldy usedSprites
    lda explosionBits,y
    ora explosionXHigh
    sta explosionXHigh
    jmp !y+
!lowOnly:
    lda explosionXLo,y
    sta slotX,x
!y:
    ldy explosionPiece
    lda explosionYLo,y
    sta slotY,x
    ldy usedSprites
    lda explosionBits,y
    ora explosionEnabled
    sta explosionEnabled
    jmp facePositionDone

advanceExplosion:
    lda angleYaw
    clc
    adc #6
    sta angleYaw
    lda anglePitch
    clc
    adc #4
    sta anglePitch
    ldx #0
!piece:
    lda explosionXLo,x
    clc
    adc explosionVelocityX,x
    sta explosionXLo,x
    lda explosionXHi,x
    adc explosionVelocityXHi,x
    sta explosionXHi,x
    lda explosionYLo,x
    clc
    adc explosionVelocityY,x
    sta explosionYLo,x
    lda explosionYHi,x
    adc explosionVelocityYHi,x
    sta explosionYHi,x
    inx
    cpx explosionCount
    bne !piece-
    inc explosionAge
    lda explosionAge
    cmp #45
    bcc !done+
    lda #1
    sta explosionDone
!done:
    rts

explosionAge: .byte 0
explosionDone: .byte 0
explosionCount: .byte 0
explosionScan: .byte 0
explosionPiece: .byte 0
explosionEnabled: .byte 0
explosionXHigh: .byte 0
explosionScale: .byte 64
explosionFaces: .fill 8, 0
explosionXLo: .fill 8, 0
explosionXHi: .fill 8, 0
explosionYLo: .fill 8, 0
explosionYHi: .fill 8, 0
explosionVelocityX: .byte -12,-4,6,14,12,2,-8,-14
explosionVelocityY: .byte -10,-14,-12,-4,8,14,12,2
explosionVelocityXHi: .byte $ff,$ff,0,0,0,0,$ff,$ff
explosionVelocityYHi: .byte $ff,$ff,$ff,$ff,0,0,0,0
explosionBits: .byte 1,2,4,8,16,32,64,128
.errorif * > $cc34, "Detached fragments overlap fill B tail"
