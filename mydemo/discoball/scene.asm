// The controller changes render state only between completed publications.
sceneInit:
    lda #0
    sta sceneState
    sta sceneBallActive
    sta sceneTicks
    sta sceneTicks+1
    sta sceneOutroRequested
    sta sceneZoomScale
    lda #$ff
    sta $dc02
    lda #0
    sta $dc03
    jsr fadeInit
    jmp beginFadeIn

// Redirect the two verified STA $D418 sites to a value-preserving shadow store.
// JSR, the original store, the shadow store and RTS add 16 clocks per SID write.
scenePatchMusic:
    lda #$20
    sta MUSIC_LOAD+$005c
    sta MUSIC_LOAD+$02a8
    lda #<sceneSidWrite
    sta MUSIC_LOAD+$005d
    sta MUSIC_LOAD+$02a9
    lda #>sceneSidWrite
    sta MUSIC_LOAD+$005e
    sta MUSIC_LOAD+$02aa
    rts

// CIA1 port A selects keyboard column seven; SPACE is port B bit four.
scenePalTick:
    lda sceneState
    cmp #SCENE_DONE
    beq !done+
    inc sceneTicks
    bne !keyboard+
    inc sceneTicks+1
!keyboard:
    cmp #SCENE_EXPLODE
    bcs !done+
    lda #$7f
    sta $dc00
    lda $dc01
    and #$10
    bne !released+
    lda #1
    sta sceneOutroRequested
!released:
    lda #$ff
    sta $dc00
!done:
    rts

sceneService:
    lda sceneOutroRequested
    beq !dispatch+
    lda sceneState
    cmp #SCENE_EXPLODE
    bcs !dispatch+
    jsr sceneBeginOutro
!dispatch:
    ldx sceneState
    lda sceneServicesLow,x
    sta sceneDispatch+1
    lda sceneServicesHigh,x
    sta sceneDispatch+2
sceneDispatch:
    jmp $ffff

sceneFadeIn:
    lda fadeBusy
    bne sceneReturn
    lda #SCENE_ZOOM_IN
    jsr sceneSetState
    lda #1
    sta sceneBallActive
    // First publication must be field A, allowing at least two PAL ticks.
    lda rasterTick
    and #1
    eor #1
    clc
    adc #2
    sta presentationCountdown
sceneReturn:
    rts

sceneZoomIn:
    lda sceneTicks+1
    bne sceneEnterRun
    lda sceneTicks
    cmp #100
    bcs sceneEnterRun
    tax
    lda sceneZoomTable,x
    sta sceneZoomScale
    rts

sceneEnterRun:
    lda #SCENE_RUN
    jsr sceneSetState
    lda #0
    sta angleYaw
    sta anglePitch
    sta motionPhase
    sta yawFraction
    sta pitchFraction
    sta zoomPhase
    sta shapeMode
    sta shapePose
    sta shownShapeMode
    lda #8
    sta yawSpeed
    lda #4
    sta pitchSpeed
    lda #64
    sta sceneZoomScale
sceneRunning:
    rts

sceneRun:
    lda sceneTicks+1
    cmp #>9022
    bcc sceneReturn
    bne sceneBeginOutro
    lda sceneTicks
    cmp #<9022
    bcc sceneReturn

sceneBeginOutro:
    lda #0
    sta sceneOutroRequested
    lda sceneBallActive
    beq !noBall+
    lda sceneState
    cmp #SCENE_ZOOM_IN
    bne !explode+
    lda sceneZoomScale
    beq !noBall+
!explode:
    jsr prepareMatrix
    jsr applyZoom
    lda #SCENE_EXPLODE
    jsr sceneSetState
    // Capture and the first detached render share an extra two PAL frames.
    lda #4
    sta presentationCountdown
    jsr beginExplosion
    jmp beginFadeOut
!noBall:
    lda #SCENE_FADE_OUT
    jsr sceneSetState
    jmp beginFadeOut

sceneExplode:
    lda explosionDone
    bne !finished+
    rts
!finished:
    lda #SCENE_FADE_OUT
    jsr sceneSetState
    lda #0
    sta sceneBallActive
    sta $d015
    rts

sceneFadeOut:
    lda fadeBusy
    beq !finished+
    rts
!finished:
    lda #SCENE_DONE
    jsr sceneSetState
    lda #0
    sta sceneBallActive
    sta $d015
    sta $d418
    sta $d404
    sta $d40b
    sta $d412
    rts

sceneSetState:
    sta sceneState
    lda #0
    sta sceneTicks
    sta sceneTicks+1
    rts

sceneServicesLow:
    .byte <sceneFadeIn,<sceneZoomIn,<sceneRun,<sceneExplode,<sceneFadeOut,<sceneReturn
sceneServicesHigh:
    .byte >sceneFadeIn,>sceneZoomIn,>sceneRun,>sceneExplode,>sceneFadeOut,>sceneReturn
sceneState: .byte SCENE_FADE_IN
sceneBallActive: .byte 0
sceneTicks: .word 0
sceneOutroRequested: .byte 0
sceneZoomScale: .byte 0

// Only the outro uses this compact loop; normal rendering keeps its hot path.
.macro SceneFadeSpriteColors() {
    lda fadeLevel
    asl
    asl
    asl
    asl
    sta sceneFadeIndex
    ldx shownMetadataBase
    ldy #0
!slot:
    sty sceneColorSlot
    lda rasterTick
    and #1
    beq !darker+
    lda slotColor,x
    jmp !map+
!darker:
    ldy slotColor,x
    lda spriteDarkerColors,y
!map:
    ora sceneFadeIndex
    tay
    lda fadeSpriteColors,y
    ldy sceneColorSlot
    sta $d027,y
    inx
    iny
    cpy #8
    bne !slot-
    rts
sceneFadeIndex: .byte 0
sceneColorSlot: .byte 0
}
