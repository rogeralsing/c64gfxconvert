// Main-loop fader. Sources and packed lookup pages beneath I/O are read with
// $01=$34; IRQs must temporarily restore $35 and then restore the interrupted map.
// All state and address patches belong to this service; renderer zero page survives.

fadeInit:
    lda #$35
    sta $01
    lda #0
    sta fadeLevel
    sta fadeWorkLevel
    sta fadeTarget
    sta fadeBusy
    ldx #0
!black:
    .for (var page=0; page<4; page++) {
        sta $0400+page*$100,x
        sta $7c00+page*$100,x
        sta $d800+page*$100,x
    }
    inx
    bne !black-
    rts

beginFadeIn:
    lda #7
    bne fadeBegin
beginFadeOut:
    lda #0
fadeBegin:
    sta fadeTarget
    cmp fadeLevel
    bne !begin+
    // A partial pass may already differ from the last completed level.
    lda fadeBusy
    bne !begin+
    rts
!begin:
    lda #1
    sta fadeBusy
    lda rasterTick
    sta fadeTick
    lda #50
    sta fadeQuota
    lda #0
    ldx fadeLevel
    cpx fadeTarget
    beq !direction+
    lda #1
    bcc !direction+
    lda #$ff
!direction:
    sta fadeDirection

fadeNextLevel:
    lda fadeLevel
    clc
    adc fadeDirection
    sta fadeWorkLevel
    clc
    adc #$d4
    sta fadeLookupA+2
    sta fadeLookupB+2
    sta fadeLookupColor+2
    lda #0
    sta fadeIndex
    lda #$94
    sta fadeReadA+2
    lda #$d0
    sta fadeReadB+2
    lda #$10
    sta fadeReadColor+2
    lda #$04
    sta fadeWriteA+2
    lda #$7c
    sta fadeWriteB+2
    lda #$d8
    sta fadeWriteColor+2
    lda #<$03e8
    sta fadeRemaining
    lda #>$03e8
    sta fadeRemaining+1
    rts

// Process at most fifty cells per PAL tick and exactly one cell per call.
fadeService:
    lda fadeBusy
    bne !active+
    rts
!active:
    lda rasterTick
    cmp fadeTick
    beq !quota+
    sta fadeTick
    lda #50
    sta fadeQuota
!quota:
    lda fadeQuota
    bne !tile+
    rts
!tile:
    dec fadeQuota
    ldx fadeIndex
    lda #$34
    sta $01
fadeReadA:
    ldy $9400,x
fadeLookupA:
    lda $d400,y
fadeWriteA:
    sta $0400,x
fadeReadB:
    ldy $d000,x
fadeLookupB:
    lda $d400,y
fadeWriteB:
    sta $7c00,x
fadeReadColor:
    ldy $1000,x
fadeLookupColor:
    lda $d400,y
    sta fadeColor
    lda #$35
    sta $01
    lda fadeColor
fadeWriteColor:
    sta $d800,x
    inc fadeIndex
    bne !remaining+
    inc fadeReadA+2
    inc fadeReadB+2
    inc fadeReadColor+2
    inc fadeWriteA+2
    inc fadeWriteB+2
    inc fadeWriteColor+2
!remaining:
    lda fadeRemaining
    bne !low+
    dec fadeRemaining+1
!low:
    dec fadeRemaining
    lda fadeRemaining
    ora fadeRemaining+1
    bne !return+
    lda fadeWorkLevel
    sta fadeLevel
    cmp fadeTarget
    beq !finished+
    jmp fadeNextLevel
!finished:
    lda #0
    sta fadeBusy
!return:
    rts

fadeLevel: .byte 0
fadeWorkLevel: .byte 0
fadeTarget: .byte 0
fadeDirection: .byte 1
fadeBusy: .byte 0
fadeTick: .byte 0
fadeQuota: .byte 0
fadeIndex: .byte 0
fadeRemaining: .word 0
fadeColor: .byte 0
