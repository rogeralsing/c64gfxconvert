// Third part: retain the native music while Spindle loads both unchanged MCI
// fields, then use the static PAL phase switch from mci-viewer/player.asm.
// Everything referenced after the handoff lives here or in protected music RAM.
.import source "assets/mci.asm"
.const MCI_LOADER = $ce00

beginMciPart:
    sei
    lda frameCounter
    sta mciMusicFrame
    lda frameCounter + 1
    sta mciMusicFrame + 1
    lda #1
    sta mciState
    sta mciLoadStage
    jsr mciFreezeCorners
    lda #$35
    sta $01
    lda #<mciMusicIrq
    sta $fffe
    lda #>mciMusicIrq
    sta $ffff
    lda #<mciNmi
    sta $fffa
    lda #>mciNmi
    sta $fffb
    lda #64
    sta $d012
    lda $d011
    and #$7f
    sta $d011
    lda #1
    sta $d019
    sta $d01a
    cli

    // The first job leaves the frozen first bitmap and its palette visible.
    jsr MCI_LOADER
    lda #2
    sta mciLoadStage
    lda #0
    sta $d015
    lda #$0b
    sta $d011
    jsr MCI_LOADER
    lda #3
    sta mciLoadStage

    ldx #0
!copyColors:
    .for (var page = 0; page < 3; page++) {
        lda MCI_COLOR_SOURCE + page * $100,x
        sta $d800 + page * $100,x
    }
    inx
    bne !copyColors-
!copyColorTail:
    lda MCI_COLOR_SOURCE + $300,x
    sta $db00,x
    inx
    cpx #232
    bne !copyColorTail-
    lda #MCI_BACKGROUND
    sta $d020
    sta $d021
    lda #$18
    sta $d018
    sta $d016
    lda #$3c
    sta $dd02
    lda #0
    sta mciPhase
    sta mciFieldCounter
    sta mciFieldCounter + 1
!waitRevealFrameStart:
    bit $d011
    bmi !waitRevealFrameStart-
!waitRevealBorder:
    bit $d011
    bpl !waitRevealBorder-
    lda #$3b
    sta $d011
    lda #2
    sta mciState
    lda #4
    sta mciLoadStage
    jmp mciWaitFrameStart

mciWaitFrame:
    bit $d011
    bpl mciWaitFrame
mciFrameComplete:
    // mciPhase describes the complete field, not the field selected next.
    inc mciFieldCounter
    bne !fieldCounted+
    inc mciFieldCounter + 1
!fieldCounted:
    lda mciPhase
    eor #1
    sta mciPhase
    tax
    lda mciBankDirections,x
    sta $dd02
    lda mciScrollValues,x
    sta $d016
mciWaitFrameStart:
    bit $d011
    bmi mciWaitFrameStart
    jmp mciWaitFrame

mciMusicIrq:
    pha
    txa
    pha
    tya
    pha
    lda $01
    pha
    lda #$35
    sta $01
    lda #1
    sta $d019
    inc mciMusicFrame
    bne !musicCounted+
    inc mciMusicFrame + 1
!musicCounted:
mciMusicStart:
    jsr MUSIC_PLAY
mciMusicDone:
    pla
    sta $01
    pla
    tay
    pla
    tax
    pla
    rti

mciFreezeCorners:
    // Both enemies have left the final viewport. Slot 6 holds the bottom-left
    // mask so the frozen picture no longer needs the old raster multiplex.
    lda #(CORNER_SPRITES / 64) + 2
    sta SCREEN + $3fe
    lda #ACTOR_X_BASE
    sta $d00c
    lda #ACTOR_Y_BASE + TV_HEIGHT * 8 - 21
    sta $d00d
    lda #0
    sta $d02d
    lda $d01c
    and #$bf
    sta $d01c
    lda $d010
    and #$bf
    sta $d010
    lda $d015
    ora #$40
    sta $d015
    rts

mciNmi:
    rti
mciBankDirections: .byte $3c, $3e
mciScrollValues: .byte $18, $19
mciState: .byte 0
mciLoadStage: .byte 0
mciPhase: .byte 0
mciFieldCounter: .word 0
mciMusicFrame: .word 0
mciResidentEnd:
