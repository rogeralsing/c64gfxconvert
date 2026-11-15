// The second room replaces the picture after both finite stage runs.
// Decode a bounded number of output bytes per PAL frame so music keeps ticking.
.const ENDING_BYTES_PER_FRAME = 160
.const ENDING_INPUT = $fb
.const ENDING_OUTPUT = $fd

beginEnding:
    lda #1
    sta endingState
    lda #0
    sta $d015
    lda #$0b
    sta $d011
    // The startup decoder's RAM vectors point into the reused corner workspace.
    // Give the temporary KERNAL-out interval a permanent, harmless NMI target.
    lda #<endingNmi
    sta $fffa
    sta $fffe
    lda #>endingNmi
    sta $fffb
    sta $ffff
    lda #<(endingPackedEnd - 1)
    sta ENDING_INPUT
    lda #>(endingPackedEnd - 1)
    sta ENDING_INPUT + 1
    lda #0
    sta endingSegment
    sta endingRunCount
    ldy #0
    jsr endingSelectSegment
    rts

updateEnding:
    lda endingSegment
    cmp #4
    bne !notRefilling+
    jmp refillSecondRoom
!notRefilling:
    cmp #3
    bne !decode+
    jmp prepareSecondRoom
!decode:
    // $35 exposes the packed KERNAL-area RAM and keeps SID/Color RAM visible.
    lda #$35
    sta $01
    ldx #256 - ENDING_BYTES_PER_FRAME
!nextByte:
    lda endingRunCount
    bne !packetReady+
    jsr endingReadPrevious
    sta endingRunMode
    and #$7f
    clc
    adc #1
    sta endingRunCount
    bit endingRunMode
    bpl !packetReady+
    jsr endingReadPrevious
    sta endingRunValue
!packetReady:
    bit endingRunMode
    bmi !repeat+
    jsr endingReadPrevious
    jmp !plot+
!repeat:
    lda endingRunValue
!plot:
    ldy endingSegment
    bne !singlePixel+
    // A packed pair holds the even cell in its high nibble. Backwards output
    // writes the odd cell first; Color RAM ignores the stored high nibble.
    pha
    ldy #0
    sta (ENDING_OUTPUT),y
    dec ENDING_OUTPUT
    inx
    pla
    lsr
    lsr
    lsr
    lsr
!singlePixel:
    ldy #0
    sta (ENDING_OUTPUT),y
    dec endingRunCount
    ldy ENDING_OUTPUT
    bne !sameOutputPage+
    dec ENDING_OUTPUT + 1
    dec ENDING_OUTPUT
    ldy endingSegment
    lda ENDING_OUTPUT + 1
    cmp endingStopHigh,y
    bne !budget+
    inc endingSegment
    ldy endingSegment
    cpy #3
    beq !return+
    jsr endingSelectSegment
    jmp !budget+
!sameOutputPage:
    dec ENDING_OUTPUT
!budget:
    inx
    bne !nextByte-
!return:
    lda #$36
    sta $01
    rts

endingReadPrevious:
    ldy #0
    lda (ENDING_INPUT),y
    ldy ENDING_INPUT
    bne !sameInputPage+
    dec ENDING_INPUT + 1
!sameInputPage:
    dec ENDING_INPUT
    rts

endingSelectSegment:
    lda endingDestinationLow,y
    sta ENDING_OUTPUT
    lda endingDestinationHigh,y
    sta ENDING_OUTPUT + 1
    rts

endingNmi:
    rti

prepareSecondRoom:
    lda #0
    sta activeLevel
    jsr selectLevel
    lda terrainScreenColors
    ldy #5
    jsr setTVColors
    jsr maskTVEdges
    jsr prepareColumn
    lda #TV_PIXELS
    sta levelTransition
    lda #4
    sta endingSegment
    rts

refillSecondRoom:
    lda levelTransition
    beq revealSecondRoom
    jsr scrollTerrain
    dec levelTransition
    rts

revealSecondRoom:
    jsr updateColors
    jsr updateSprites
    // Original room colors already represent lighting level zero.
    lda #0
    sta lightLevel
    sta lightPhase
    lda #13
    sec
    sbc frameCounter
    and #15
    bne !lightCountdown+
    lda #LIGHT_FRAME_INTERVAL
!lightCountdown:
    sta lightCountdown
    lda frameCounter
    and #3
    eor #3
    bne !scrollCountdown+
    lda #SCROLL_FRAME_INTERVAL
!scrollCountdown:
    sta scrollCountdown
    lda #ENDING_BACKGROUND
    sta $d021
    lda #$3b
    sta $d011
    lda #2
    sta endingState
    rts

// The stream is read backwards: packed color pairs, screen, then bitmap.
endingDestinationLow: .byte <$dbe7, <$07e7, <$3f3f
endingDestinationHigh: .byte >$dbe7, >$07e7, >$3f3f
endingStopHigh: .byte $d7, $03, $1f
endingState: .byte 0
endingSegment: .byte 0
endingRunCount: .byte 0
endingRunMode: .byte 0
endingRunValue: .byte 0
