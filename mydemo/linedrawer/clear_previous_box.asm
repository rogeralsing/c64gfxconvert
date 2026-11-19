// Keep the previous draw bounds for each screen pair. The pair about to
// become visible still contains its own image from two frames earlier.
.label boxMinX = $e6
.label boxMaxX = $e7
.label boxMinY = $e8
.label boxMaxY = $e9
.label boxEndCode = $ea
.label boxStopX = $ec
.label boxStartX = $ed

.macro ClearBoxRows(screenAddress) {
    .for (var row = 0; row < 25; row++) {
        sta screenAddress + row * 40,x
    }
    jmp boxNextColumn
}

*=$a400 "Bounds clear rows A"
boxRowsA:
ClearBoxRows(SCREEN)
*=$a500 "Bounds clear rows B"
boxRowsB:
ClearBoxRows(SCREEN_B)

*=$a600 "Previous frame bounds clear"
clearPreviousBox:
    ldx backPair
    lda boxRightColumn,x
    bmi !fresh+
    sta boxStartX
    lda boxBeforeLeftColumn,x
    sta boxStopX
    lda boxFirstRowOffset,x
    sta boxEnterRow+1
    lda boxAfterLastRowOffset,x
    sta boxEndCode
    lda boxRowPages,x
    sta boxEnterRow+2
    sta boxEndCode+1

    // Skip the rows after the previous frame's box. Restore the patched
    // instruction before this code is used to clear either pair again.
    ldy #0
    lda (boxEndCode),y
    pha
    lda #$4c
    sta (boxEndCode),y
    iny
    lda (boxEndCode),y
    pha
    lda #<boxNextColumn
    sta (boxEndCode),y
    iny
    lda (boxEndCode),y
    pha
    lda #>boxNextColumn
    sta (boxEndCode),y

    ldx boxStartX
    lda #0
    jsr boxEnterRow

    ldy #2
    pla
    sta (boxEndCode),y
    dey
    pla
    sta (boxEndCode),y
    dey
    pla
    sta (boxEndCode),y
!fresh:
    rts

boxNextColumn:
    dex
    cpx boxStopX
    beq !done+
boxEnterRow:
    jmp $ffff
!done:
    rts

boxRowPages:
    .byte >boxRowsA, >boxRowsB
boxRightColumn:
    .byte $ff, $ff
boxBeforeLeftColumn:
    .byte 0, 0
boxFirstRowOffset:
    .byte 0, 0
boxAfterLastRowOffset:
    .byte 0, 0

*=$b900 "Capture clipped cube bounds"
rememberCubeBox:
    lda #$ff
    sta boxMinX
    sta boxMinY
    lda #0
    sta boxMaxX
    sta boxMaxY
    ldy #0
!point:
    // Clamp the signed projected coordinates to the inclusive viewport.
    // This conservatively encloses even edges clipped at a screen border.
    lda PTAB_HI,y
    beq !lowX+
    bmi !negativeX+
    bpl !right+
!lowX:
    lda PTAB,y
    cmp #160
    bcc !x+
!right:
    lda #159
    bne !x+
!negativeX:
    lda #0
!x:
    cmp boxMinX
    bcs !maxX+
    sta boxMinX
!maxX:
    cmp boxMaxX
    bcc !nextAxis+
    sta boxMaxX
!nextAxis:
    lda PTAB_HI+1,y
    beq !lowY+
    bmi !negativeY+
    bpl !bottom+
!lowY:
    lda PTAB+1,y
    cmp #100
    bcc !y+
!bottom:
    lda #99
    bne !y+
!negativeY:
    lda #0
!y:
    cmp boxMinY
    bcs !maxY+
    sta boxMinY
!maxY:
    cmp boxMaxY
    bcc !nextPoint+
    sta boxMaxY
!nextPoint:
    iny
    iny
    cpy #16
    bne !point-

    ldx backPair
    lda boxMaxX
    lsr
    lsr
    sta boxRightColumn,x
    lda boxMinX
    lsr
    lsr
    sec
    sbc #1
    sta boxBeforeLeftColumn,x

    lda boxMinY
    lsr
    lsr
    tay
    lda boxRowOffsets,y
    sta boxFirstRowOffset,x
    lda boxMaxY
    lsr
    lsr
    tay
    lda boxRowOffsets+1,y
    sta boxAfterLastRowOffset,x
    rts

boxRowOffsets:
    .fill 26, i*3
