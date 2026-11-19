// Signed screen coordinates use the existing low-byte endpoint slots and
// these four high bytes. An endpoint on the display fits in the low byte.
.label clipX0Hi = $aa
.label clipY0Hi = $ab
.label clipX1Hi = $ac
.label clipY1Hi = $ad

.label clipPoints = $ae       // original x0, y0, x1, y1 (four signed words)
.label clipCode0 = $b6
.label clipCode1 = $b7
.label clipEndOffset = $b8
.label clipEndCode = $b9
.label clipPointBits = $ba
.label clipX = $bb
.label clipY = $bc

.const CLIP_LEFT = 1
.const CLIP_RIGHT = 2
.const CLIP_TOP = 4
.const CLIP_BOTTOM = 8

*=$7400 "Viewport line clipping"
.import source "clip_math.asm"

// Draw the visible part of a signed line in the current screen/charset.
// Intersections are tested before rounding them to logical pixels.
// Clobbers A/X/Y and the endpoint low bytes. A rejected line writes nothing.
drawClippedLine:
    lda clipX0Hi
    ora clipY0Hi
    ora clipX1Hi
    ora clipY1Hi
    bne clipLineSlow
    lda #159
    cmp lx0
    bcc clipLineSlow
    cmp lx1
    bcc clipLineSlow
    lda #99
    cmp ly0
    bcc clipLineSlow
    cmp ly1
    bcc clipLineSlow
    jmp drawCharLine

clipLineSlow:
    lda lx0
    sta clipPoints
    lda clipX0Hi
    sta clipPoints+1
    lda ly0
    sta clipPoints+2
    lda clipY0Hi
    sta clipPoints+3
    lda lx1
    sta clipPoints+4
    lda clipX1Hi
    sta clipPoints+5
    lda ly1
    sta clipPoints+6
    lda clipY1Hi
    sta clipPoints+7

    ldx #0
    jsr clipPointCode
    sta clipCode0
    ldx #4
    jsr clipPointCode
    sta clipCode1
    and clipCode0
    bne !reject+              // Both endpoints are beyond the same side.

    lda clipCode0
    beq !end+
    ldx #0
    jsr clipEndpoint
    bcc !reject+
    lda clipX
    sta lx0
    lda clipY
    sta ly0
!end:
    lda clipCode1
    beq !visible+
    ldx #4
    jsr clipEndpoint
    bcc !reject+
    lda clipX
    sta lx1
    lda clipY
    sta ly1
!visible:
    jmp drawCharLine
!reject:
    rts

// X = 0 or 4 into clipPoints. Return the sides on which the point is outside.
clipPointCode:
    lda #0
    sta clipPointBits
    lda clipPoints+1,x
    bmi !left+
    bne !right+
    lda clipPoints,x
    cmp #160
    bcc !vertical+
!right:
    lda #CLIP_RIGHT
    bne !horizontal+
!left:
    lda #CLIP_LEFT
!horizontal:
    sta clipPointBits
!vertical:
    lda clipPoints+3,x
    bmi !top+
    bne !bottom+
    lda clipPoints+2,x
    cmp #100
    bcc !done+
!bottom:
    lda #CLIP_BOTTOM
    bne !combined+
!top:
    lda #CLIP_TOP
!combined:
    ora clipPointBits
    rts
!done:
    lda clipPointBits
    rts

// One endpoint outside. Test its X side, then its Y side, if present.
// The first valid intersection lies on the edge of the visible segment.
// Always use the original line, even when the other endpoint was clipped.
clipEndpoint:
    stx clipEndOffset
    sta clipEndCode
    and #(CLIP_LEFT | CLIP_RIGHT)
    beq !vertical+
    and #CLIP_LEFT
    beq !maxX+
    lda #0
    beq !tryX+
!maxX:
    lda #159
!tryX:
    sta clipX
    sta clipBound
    lda #99
    sta clipLimit
    ldy #0
    jsr clipAxis
    bcc !vertical+
    sta clipY
    rts
!vertical:
    lda clipEndCode
    and #(CLIP_TOP | CLIP_BOTTOM)
    beq !miss+
    and #CLIP_TOP
    beq !maxY+
    lda #0
    beq !tryY+
!maxY:
    lda #99
!tryY:
    sta clipY
    sta clipBound
    lda #159
    sta clipLimit
    ldy #2
    jsr clipAxis
    bcc !miss+
    sta clipX
    rts
!miss:
    clc
    rts

// Y = 0 for an X boundary, 2 for a Y boundary. Flip bit 2 of
// the index for the other endpoint and bit 1 for the other axis.
clipAxis:
    tya
    ora clipEndOffset
    tax
    lda clipPoints,x
    sta clipFromAxis
    lda clipPoints+1,x
    sta clipFromAxis+1
    txa
    eor #4
    tax
    lda clipPoints,x
    sta clipToAxis
    lda clipPoints+1,x
    sta clipToAxis+1
    txa
    eor #2
    tax
    lda clipPoints,x
    sta clipToOther
    lda clipPoints+1,x
    sta clipToOther+1
    txa
    eor #4
    tax
    lda clipPoints,x
    sta clipFromOther
    lda clipPoints+1,x
    sta clipFromOther+1
    jmp clipIntersection

clipLineEnd:
.assert "Viewport clipper stays below projection data", clipLineEnd <= $8000, true
