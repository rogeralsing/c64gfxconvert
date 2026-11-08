// Native PAL C64 parallax experiment using extracted Rimrunner world and actor data.
// Each horizontal band owns its character rows. Its copy runs after its last scanline.
// Raster IRQs retain the world's palette/charset changes while those copies run.

.const SCREEN = $4000
.const MAP_COLUMNS = 40
.const RIDER_X = 112
.const RIDER_Y = 151

BasicUpstart2(start)

start:
    sei
    cld
    lda #$2f
    sta $00
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    sta $d020
    sta $d021
    sta paused
    sta spaceHeld
    sta frameCounter
    sta frameCounter+1
    sta motionCounter
    sta animationFrame
    sta coarseBack
    sta coarseMiddle
    sta coarseNear
    sta farDone
    sta middleDone
    sta nearDone
    lda #$0f
    sta $d019
    lda #$0b
    sta $d011

    // Keep RESTORE harmless with the KERNAL ROM switched out.
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda #<irq
    sta $fffe
    lda #>irq
    sta $ffff
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    ora #2
    sta $dd00                       // VIC bank $4000-$7fff has no character-ROM hole.

    // The new test header uses ROM glyphs; the two world character sets stay intact.
    // Character ROM appears at $d000 only while I/O is temporarily switched out.
    lda #$33
    sta $01
    ldx #0
copyFont:
    .for (var page = 0; page < 4; page++) {
        lda $d000 + page * $100,x
        sta headerCharset + page * $100,x
    }
    inx
    bne copyFont
    lda #$35
    sta $01

    ldx #0
clearScreen:
    lda #32
    .for (var page = 0; page < 4; page++) {
        sta SCREEN + page * $100,x
    }
    lda #0
    .for (var page = 0; page < 4; page++) {
        sta $d800 + page * $100,x
    }
    inx
    bne clearScreen

    ldx #0
initializeLandscape:
    .for (var row = 5; row < 25; row++) {
        lda worldMap + row * MAP_COLUMNS,x
        sta SCREEN + row * 40,x
        lda worldColors + row * MAP_COLUMNS,x
        and #15
        sta $d800 + row * 40,x
    }
    inx
    cpx #40
    beq landscapeReady
    jmp initializeLandscape
landscapeReady:
    ldx #0
writeTitle:
    lda title,x
    sta SCREEN + 2,x
    lda #3
    sta $d800 + 2,x
    inx
    cpx #titleEnd-title
    bne writeTitle
    ldx #0
writeInstructions:
    lda instructions,x
    sta SCREEN + 40 + 2,x
    lda #7
    sta $d800 + 40 + 2,x
    inx
    cpx #instructionsEnd-instructions
    bne writeInstructions

    lda #7
    sta fineBack
    sta fineMiddle
    sta fineNear
    lda #$06
    sta $d018                       // Screen $4000, header charset $5800.
    lda #$10
    sta $d016                       // Multicolor characters, 38-column viewport.
    lda #0
    sta $d010
    sta $d017
    sta $d01b
    sta $d01d
    sta $d025
    lda #13
    sta $d026
    lda #$7f
    sta $d01c
    sta $d015                       // Seven independent tiles; no sprite multiplexing.
    .for (var slot = 0; slot < 7; slot++) {
        lda mountedOffsets + slot * 2
        clc
        adc #RIDER_X
        sta $d000 + slot * 2
        lda mountedOffsets + slot * 2 + 1
        clc
        adc #RIDER_Y
        sta $d001 + slot * 2
        lda #5
        sta $d027 + slot
        lda #$80 + slot
        sta SCREEN+$3f8+slot
    }

    // One keyboard matrix column is enough for SPACE, PB bit 4 in PA column 7.
    lda #$ff
    sta $dc02
    sta $dc00
    lda #0
    sta $dc03
    lda #$1b
    sta $d011
    NextIRQ(40, irqHeader)
    lda #1
    sta $d01a
    cli

main:
    // IRQ flags cannot be missed while a rare coarse copy spans several raster events.
    // The captured world has one constant Color RAM value per row. It needs no color copy.
!waitFar:
    lda farDone
    beq !waitFar-
    lda #0
    sta farDone
    jsr updateBack
!waitMiddle:
    lda middleDone
    beq !waitMiddle-
    lda #0
    sta middleDone
    jsr updateMiddle
!waitNear:
    lda nearDone
    beq !waitNear-
    lda #0
    sta nearDone
    jsr updateNear
    lda paused
    bne !noMotion+
    inc motionCounter
!noMotion:
    jmp main

irq:
    pha
    txa
    pha
    tya
    pha
    lda #1
    sta $d019
irqDispatch:
    jmp irqHeader

irqHeader:
    lda #$06
    sta $d018
    lda #$10
    sta $d016
    lda #0
    sta $d021
    sta $d01b
    lda #14
    sta $d022
    lda #6
    sta $d023
    jsr readSpace
    // Eight original running poses advance every two PAL fields, including the rider.
    lda motionCounter
    lsr
    and #7
    sta animationFrame
    asl
    asl
    asl
    clc
    adc #$80
    tax
    .for (var slot = 0; slot < 7; slot++) {
        stx SCREEN+$3f8+slot
        inx
    }
    inc frameCounter
    bne !counted+
    inc frameCounter+1
!counted:
frameComplete:
    // Fixed checkpoint inside IRQ40. Previous field's copies and current actor pose are ready.
    NextIRQ(90, irqFar)
    jmp irqReturn

irqFar:
    lda #$02
    sta $d018
    lda fineBack
    ora #$10
    sta $d016
    lda #0
    sta $d021
    lda #14
    sta $d022
    lda #3
    sta $d023
    NextIRQ(178, irqMiddle)
    jmp irqReturn

irqMiddle:
    // Finish palette/charset writes before the next badline stalls the CPU.
    // Their setup places the final fine-scroll store in the preceding right border.
    lda #$04
    sta $d018
    lda #4
    sta $d021
    lda #11
    sta $d023
    lda fineMiddle
    ora #$10
    sta $d016
    lda #1
    sta farDone
    NextIRQ(198, irqRoadPalette)
    jmp irqReturn

irqRoadPalette:
    lda #11
    sta $d021
    NextIRQ(210, irqNear)
    jmp irqReturn

irqNear:
    BorderDelay()
    lda fineNear
    ora #$10
    sta $d016
    lda #$7f
    sta $d01b                       // The frontmost ground can cover the actor's feet.
    lda #1
    sta middleDone
    NextIRQ(216, irqNearPalette)
    jmp irqReturn

irqNearPalette:
    lda #0
    sta $d022
    lda #3
    sta $d023
    NextIRQ(252, irqBottom)
    jmp irqReturn

irqBottom:
    lda #1
    sta nearDone
    NextIRQ(40, irqHeader)
irqReturn:
    pla
    tay
    pla
    tax
    pla
    rti

updateBack:
    lda paused
    beq !advance+
    rts
!advance:
    AdvanceBand(5, 11, coarseBack, fineBack, 2)
    rts

updateMiddle:
    lda paused
    beq !advance+
    rts
!advance:
    AdvanceBand(16, 4, coarseMiddle, fineMiddle, 4)
    rts

updateNear:
    lda paused
    beq !advance+
    rts
!advance:
    AdvanceBand(20, 5, coarseNear, fineNear, 6)
    rts

readSpace:
    lda #$7f
    sta $dc00
    lda $dc01
    and #$10
    bne !released+
    lda spaceHeld
    bne !done+
    lda #1
    sta spaceHeld
    lda paused
    eor #1
    sta paused
    beq !running+
    lda #11
!running:
    sta $d020
    jmp !done+
!released:
    lda #0
    sta spaceHeld
!done:
    lda #$ff
    sta $dc00
    rts

nmi:
    rti

frameCounter:
    .word 0
motionCounter:
    .byte 0
animationFrame:
    .byte 0
paused:
    .byte 0
spaceHeld:
    .byte 0
farDone:
    .byte 0
middleDone:
    .byte 0
nearDone:
    .byte 0
fineBack:
    .byte 7
fineMiddle:
    .byte 7
fineNear:
    .byte 7
coarseBack:
    .byte 0
coarseMiddle:
    .byte 0
coarseNear:
    .byte 0

title:
    .encoding "screencode_upper"
    .text "RIMRUNNER PARALLAX / PAL 50 HZ"
titleEnd:
instructions:
    .text "2 : 4 : 6 PX       SPACE: PAUSE"
instructionsEnd:

.assert "Runtime must remain below display bank", * < $4000, true

.macro NextIRQ(line, handler) {
    lda #<handler
    sta irqDispatch+1
    lda #>handler
    sta irqDispatch+2
    lda #line
    sta $d012
}

.macro BorderDelay() {
    .for (var delay = 0; delay < 8; delay++) {
        nop
    }
}

.macro AdvanceBand(firstRow, rows, coarse, fine, pixels) {
    lda fine
    sec
    sbc #pixels
    sta fine
    bmi !coarse+
    jmp !done+
!coarse:
    clc
    adc #8
    sta fine
    inc coarse
    lda coarse
    cmp #MAP_COLUMNS
    bcc !valid+
    lda #0
    sta coarse
!valid:
    // The complete 40-column source repeats; each coarse step reveals its next column.
    ldx #0
!shift:
    .for (var row = 0; row < rows; row++) {
        lda SCREEN + (firstRow + row) * 40 + 1,x
        sta SCREEN + (firstRow + row) * 40,x
    }
    inx
    cpx #39
    bne !shift-

    ldx coarse
    dex
    bpl !column+
    ldx #39
!column:
    .for (var row = 0; row < rows; row++) {
        lda worldMap + (firstRow + row) * MAP_COLUMNS,x
        sta SCREEN + (firstRow + row) * 40 + 39
    }
!done:
}

#import "rimrunner-parallax-assets.asm"
