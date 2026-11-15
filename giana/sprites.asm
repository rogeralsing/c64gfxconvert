// Eight hardware sprites: three corner slots (one reused), a highlight, two Giana planes and two enemies.
// Moving art occupies only 12x10 or 12x9 pixels of each 24x21 container.
.const ACTOR_DEST_POINTER = $fd
// The standalone loop never returns to BASIC or services keyboard interrupts.
// Copy here after SYS; keep the PRG load address at the BASIC entry point.
.assert "Corner frames avoid the stack and screen", CORNER_SPRITES >= $0200 && CORNER_SPRITES + $100 <= SCREEN, true
.assert "Corner frames are 64-byte aligned", CORNER_SPRITES & $3f, 0

initSprites:
    ldx #0
!copyCorners:
    lda cornerMaskFrames,x
    sta CORNER_SPRITES,x
    inx
    bne !copyCorners-
    lda #0
    sta $d015
    sta $d010
    sta $d017
    sta $d01b
    sta $d01d
    sta $d027
    sta $d028
    sta $d029
    lda #$f0
    sta $d01c
    lda #SPRITE_MC0
    sta $d025
    lda #SPRITE_MC1
    sta $d026
    // Black corners clip both the glass highlight and the game characters.
    lda #3
    sta $d02a
    lda #SPRITE_GIANA_COLOR
    sta $d02b
    lda #SPRITE_GIANA_LAYER1_COLOR
    sta $d02c
    lda #SPRITE_ENEMY_COLOR
    sta $d02d
    sta $d02e
    lda #CORNER_SPRITES / 64
    sta SCREEN + $3f8
    lda #(CORNER_SPRITES / 64) + 1
    sta SCREEN + $3f9
    lda #(CORNER_SPRITES / 64) + 3
    sta SCREEN + $3fa
    lda #tvHighlightSprite / 64
    sta SCREEN + $3fb
    lda #spriteWork0 / 64
    sta SCREEN + $3fc
    lda #spriteWork1 / 64
    sta SCREEN + $3fd
    lda #spriteWork2 / 64
    sta SCREEN + $3fe
    lda #spriteWork3 / 64
    sta SCREEN + $3ff
    lda #ACTOR_X_BASE
    sta $d000
    sta $d006
    lda #<(ACTOR_X_BASE + TV_WIDTH * 8 - 24)
    sta $d002
    sta $d004
    lda #ACTOR_Y_BASE
    sta $d001
    sta $d003
    lda #ACTOR_Y_BASE + TV_HEIGHT * 8 - 21
    sta $d005
    lda #ACTOR_Y_BASE + 3
    sta $d007
    jmp updateSprites

updateSprites:
    // Recover the nine-bit camera position after the incoming-column prefill.
    lda #0
    sta actorStepHi
    lda #$0f
    sta actorEnabled
    lda incomingTile
    sec
    sbc #TV_WIDTH
    and #TERRAIN_MAP_WIDTH - 1
    asl
    rol actorStepHi
    asl
    rol actorStepHi
    ora tilePixelX
    sta actorStepLo

    lda #SPRITE_PLAYER_X_MC
    sta actorX
    ldy actorStepLo
    lda actorStepHi
    beq !firstPathPage+
actorPlayerPathSecondRead:
    lda actorPlayerPath + $100,y
    jmp !playerFoot+
!firstPathPage:
actorPlayerPathFirstRead:
    lda actorPlayerPath,y
!playerFoot:
    sta actorFoot
    cmp #$ff
    beq !hidePlayer+
    jsr projectActorFoot
    sec
    sbc actorPlayerHeight
    clc
    adc #ACTOR_Y_BASE
    sta actorPlayerY
    lda #$ff
    sta actorMask0
    sta actorMask1
    lda #$3f
    sta actorEnabled
    bne !playerFrame+
!hidePlayer:
    lda #0
    sta actorPlayerY
    sta actorMask0
    sta actorMask1
!playerFrame:
    lda actorStepLo
    and #3
    asl
    sta actorPoseBase
    ldx #0
    jsr copyTinySprite
    lda actorPoseBase
    clc
    adc #1
    ldx #1
    jsr copyTinySprite
    lda #ACTOR_X_BASE + SPRITE_PLAYER_X_MC * 2
    sta $d008
    sta $d00a
    lda actorPlayerY
    sta $d009
    sta $d00b

    lda activeLevel
    beq !legacyEnemy+
    jmp updateLevel2Enemies
!legacyEnemy:
    lda #SPRITE_ENEMY_COLOR
    sta $d02d

    // A repeating world marker supplies a small, staged enemy encounter.
    lda actorStepLo
    and #63
    eor #$ff
    clc
    adc #41
    sta actorX
    lda actorStepHi
    lsr
    lda actorStepLo
    and #$c0
    ora #43
    ror
    tay
actorGroundRead:
    lda actorGround,y
    sta actorFoot
    cmp #$ff
    beq !hideEnemy+
    cmp #28
    bcc !hideEnemy+
    lda actorEnabled
    and #$30
    beq !hideEnemy+
    jsr setActorClip
    beq !hideEnemy+
    jsr projectActorFoot
    sec
    sbc #SPRITE_ENEMY_HEIGHT
    clc
    adc #ACTOR_Y_BASE
    sta actorEnemyY
    lda actorEnabled
    ora #$40
    sta actorEnabled
    bne !enemyFrame+
!hideEnemy:
    lda #0
    sta actorEnemyY
    sta actorMask0
    sta actorMask1
!enemyFrame:
    lda actorStepLo
    lsr
    and #1
    clc
    adc #SPRITE_ENEMY_FRAME_OFFSET
    ldx #2
    jsr copyTinySprite
    lda actorX
    asl
    clc
    adc #ACTOR_X_BASE
    sta $d00c
    lda actorEnemyY
    sta $d00d
    lda actorX
    bmi !lowEnemyX+
    cmp #24
    bcc !lowEnemyX+
    lda #$46
    bne !enemyXHigh+
!lowEnemyX:
    lda #$06
!enemyXHigh:
    sta $d010
    lda actorEnabled
    sta $d015
    rts

projectActorFoot:
    // Use the actor center to follow the terrain's fixed perspective steps.
    lda actorX
    clc
    adc #SPRITE_PLAYER_WIDTH_MC / 2
    bpl !nonnegativeCenter+
    lda #0
!nonnegativeCenter:
    cmp #40
    bcc !centerInView+
    lda #39
!centerInView:
    tax
    lda actorFoot
    cmp #28
    bcs !centerOrLower+
    cpx #12
    bcs !upperMiddle+
    clc
    adc #2
    rts
!upperMiddle:
    cpx #28
    bcs !sameFoot+
    clc
    adc #1
    rts
!centerOrLower:
    cmp #36
    bcc !sameFoot+
    cpx #20
    bcs !sameFoot+
    sec
    sbc #1
!sameFoot:
    rts

setActorClip:
    // The six-pixel multicolor canvas may enter or leave through either edge.
    lda actorX
    clc
    adc #5
    tax
    cpx #45
    bcs !outside+
    lda actorClipByte0,x
    sta actorMask0
    lda actorClipByte1,x
    sta actorMask1
    lda #1
    rts
!outside:
    lda #0
    rts

copyTinySprite:
    // A selects an immutable atlas plane; X selects a VIC-visible work buffer.
    // These copies run after TV drawing, on a different frame from scrolling.
    sta actorSourceFrame
    lda actorWorkLow,x
    sta ACTOR_DEST_POINTER
    lda actorWorkHigh,x
    sta ACTOR_DEST_POINTER + 1
    ldx actorSourceFrame
    lda actorFrameLow,x
    sta TILE_POINTER
    lda actorFrameHigh,x
    sta TILE_POINTER + 1
    ldy #63
!copy:
    lda (TILE_POINTER),y
    sta (ACTOR_DEST_POINTER),y
    dey
    bpl !copy-
    .for (var line = 0; line < SPRITE_GIANA_HEIGHT; line++) {
        ldy #line * 3
        lda (ACTOR_DEST_POINTER),y
        and actorMask0
        sta (ACTOR_DEST_POINTER),y
        iny
        lda (ACTOR_DEST_POINTER),y
        and actorMask1
        sta (ACTOR_DEST_POINTER),y
    }
    rts

.function actorClipMask(x, firstPair) {
    .var result = 0
    .for (var pair = 0; pair < 4; pair++) {
        .if (x + firstPair + pair >= 0 && x + firstPair + pair < TV_PIXELS) {
            .eval result = result | (3 << (6 - pair * 2))
        }
    }
    .return result
}

actorClipByte0: .fill 45, actorClipMask(i - 5, 0)
actorClipByte1: .fill 45, actorClipMask(i - 5, 4)
actorWorkLow: .byte <spriteWork0, <spriteWork1, <spriteWork2, <spriteWork3
actorWorkHigh: .byte >spriteWork0, >spriteWork1, >spriteWork2, >spriteWork3
actorFrameLow: .fill SPRITE_FRAME_COUNT, <(tinySpriteFrames + i * 64)
    .fill LEVEL2_ENEMY_FRAME_COUNT, <(extraEnemyFrames + i * 64)
actorFrameHigh: .fill SPRITE_FRAME_COUNT, >(tinySpriteFrames + i * 64)
    .fill LEVEL2_ENEMY_FRAME_COUNT, >(extraEnemyFrames + i * 64)
actorFrameColor:
    .fill 8, (i & 1) == 0 ? SPRITE_GIANA_COLOR : SPRITE_GIANA_LAYER1_COLOR
    .fill 2, SPRITE_ENEMY_COLOR
    .fill 2, 7
    .fill 4, 1
    .fill 6, 5
    .fill 2, 7
.assert "Every actor frame has an individual color", * - actorFrameColor, SPRITE_FRAME_COUNT + LEVEL2_ENEMY_FRAME_COUNT

actorStepLo: .byte 0
actorStepHi: .byte 0
actorEnabled: .byte 0
actorPoseBase: .byte 0
actorSourceFrame: .byte 0
actorX: .byte 0
actorFoot: .byte 0
actorPlayerY: .byte 0
actorEnemyY: .byte 0
actorMask0: .byte 0
actorMask1: .byte 0

.align $100
actorGround:
    .import binary "assets/sprite-ground.bin"
.assert "Ground table covers original character columns", * - actorGround, 256
actorPlayerPath:
    .import binary "assets/sprite-player-path.bin"
.assert "Player route covers the complete map", * - actorPlayerPath, 512

.align $40
cornerMaskFrames:
    .import binary "assets/tv-corners.bin"
.assert "Four 64-byte hires corner frames", * - cornerMaskFrames, $100
