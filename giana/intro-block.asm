// Two small source-derived patches: a one-pixel bump, then the original used
// brick. Later terrain shifts carry the changed pixels across the TV seams.
updateIntroBlock:
    lda activeLevel
    bne !done+
    lda actorStepHi
    bne !done+
    lda actorStepLo
    cmp #INTRO_HIT_STEP
    beq !bump+
    cmp #INTRO_SPENT_STEP
    bne !done+
    ldx #INTRO_SPENT_PATCH_COUNT - 1
    lda #<introSpentAddressLow
    sta introBlockLowRead + 1
    lda #>introSpentAddressLow
    sta introBlockLowRead + 2
    lda #<introSpentAddressHigh
    sta introBlockHighRead + 1
    lda #>introSpentAddressHigh
    sta introBlockHighRead + 2
    lda #<introSpentValues
    sta introBlockValueRead + 1
    lda #>introSpentValues
    sta introBlockValueRead + 2
    jmp !patch+
!bump:
    ldx #INTRO_BUMP_PATCH_COUNT - 1
    lda #<introBumpAddressLow
    sta introBlockLowRead + 1
    lda #>introBumpAddressLow
    sta introBlockLowRead + 2
    lda #<introBumpAddressHigh
    sta introBlockHighRead + 1
    lda #>introBumpAddressHigh
    sta introBlockHighRead + 2
    lda #<introBumpValues
    sta introBlockValueRead + 1
    lda #>introBumpValues
    sta introBlockValueRead + 2
!patch:
    ldy #0
introBlockLowRead:
    lda introBumpAddressLow,x
    sta TILE_POINTER
introBlockHighRead:
    lda introBumpAddressHigh,x
    sta TILE_POINTER + 1
introBlockValueRead:
    lda introBumpValues,x
    sta (TILE_POINTER),y
    dex
    bpl !patch-
!done:
    rts
introBlockCodeEnd:
.assert "Block patcher avoids the intro atlas", * <= $9d80, true
