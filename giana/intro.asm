// Camera-indexed opening choreography. Repeated draws at one camera step are
// idempotent, including startup and the second room's Level 1 restart.
.const INTRO_FRAME_OFFSET = SPRITE_FRAME_COUNT + LEVEL2_ENEMY_FRAME_COUNT

updateIntroPlayer:
    lda #SPRITE_GIANA_COLOR
    sta $d02b
    lda #SPRITE_GIANA_LAYER1_COLOR
    sta $d02c
    lda activeLevel
    bne !done+
    lda #SPRITE_GIANA_HEIGHT
    sta actorPlayerHeight
    lda actorStepHi
    bne !done+
    ldy actorStepLo
    cpy #INTRO_END_STEP
    bcs !done+
    lda introPose,y
    clc
    adc #INTRO_FRAME_OFFSET
    sta actorPoseBase
    cpy #INTRO_ELECTRIC_FIRST
    bcs !electric+
    lda #INTRO_SMALL_HEIGHT
    sta actorPlayerHeight
    // Hold a pixel back from the platform lip until the next camera update
    // also clears the small jumping pose's outstretched arm and shoe.
    cpy #64
    bcc !strikeAlignment+
    cpy #67
    bcs !strikeAlignment+
    lda #SPRITE_PLAYER_X_MC - 1
    sta actorX
    bne !jumpHeight+
!strikeAlignment:
    // One multicolor pixel clears the hanging side of the perspective seam
    // while the jump strikes the power-up brick rather than its neighbor.
    cpy #79
    bcc !jumpHeight+
    cpy #82
    bcs !jumpHeight+
    lda #SPRITE_PLAYER_X_MC + 1
    sta actorX
!jumpHeight:
    tya
    sec
    sbc #INTRO_JUMP_FIRST
    cmp #INTRO_JUMP_COUNT
    bcs !done+
    tay
    lda introJumpFoot,y
    sta actorFoot
!done:
    rts
!electric:
    tya
    sec
    sbc #INTRO_ELECTRIC_FIRST
    and #3
    tay
    lda introFlashColor,y
    sta $d02b
    lda #1
    sta $d02c
    rts

updateIntroBall:
    lda activeLevel
    bne !done+
    lda actorStepHi
    bne !done+
    lda actorStepLo
    sec
    sbc #INTRO_BALL_FIRST
    cmp #INTRO_BALL_COUNT
    bcs !done+
    sta introBallIndex
    tay
    lda introBallX,y
    sta actorX
    asl
    clc
    adc #ACTOR_X_BASE
    sta $d00e
    lda introBallY,y
    clc
    adc #ACTOR_Y_BASE
    sta $d00f
    lda #7
    sta $d02e
    jsr setActorClip
    lda actorStepLo
    and #1
    clc
    adc #INTRO_FRAME_OFFSET + INTRO_BALL_0
    ldx #3
    jsr copyTinySprite
    // Reveal only the rows above the brick while the ball emerges.
    ldy introBallIndex
    lda introBallRows,y
    sta introBallRowsToKeep
    asl
    clc
    adc introBallRowsToKeep
    tay
    lda #0
!hideRows:
    cpy #INTRO_BALL_HEIGHT * 3
    bcs !enable+
    sta spriteWork3,y
    iny
    bne !hideRows-
!enable:
    lda actorEnabled
    ora #$80
    sta actorEnabled
!done:
    rts

introBallIndex: .byte 0
introBallRowsToKeep: .byte 0
introControllerEnd:
.assert "Opening choreography avoids startup colors", * <= $c000, true
