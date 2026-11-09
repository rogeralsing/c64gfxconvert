// Native PAL C64 parallax experiment using extracted Rimrunner world and actor data.
// Each horizontal band owns its character rows. Its copy runs after its last scanline.
// Raster IRQs retain the world's palette/charset changes while those copies run.

.const SCREEN = $4000
.const BACK_COLUMNS = 80
.const MIDDLE_COLUMNS = 120
.const NEAR_COLUMNS = 188
.const TILE_POINTER = $fb
.const RIDER_X = 112
.const RIDER_Y = 151
.const SKY_CELLS = 480
.const SKY_BITMAP_BYTES = 3840

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
    sta skyBankValues+1
    ora #1
    sta skyBankValues
    and #$fc
    ora #2
    sta worldBankValue
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
        lda worldColors + row * 40,x
        and #15
        sta $d800 + row * 40,x
    }
    inx
    cpx #40
    beq landscapeReady
    jmp initializeLandscape
landscapeReady:
    lda #0
    sta drawColumn
initializeColumns:
    lda drawColumn
    jsr readBackColumn
    ldx drawColumn
    .for (var row = 0; row < 12; row++) {
        lda columnData + row
        sta SCREEN + (5 + row) * 40,x
    }
    lda drawColumn
    jsr readMiddleColumn
    ldx drawColumn
    .for (var row = 0; row < 2; row++) {
        lda columnData + row
        sta SCREEN + (17 + row) * 40,x
    }
    lda #0
    sta SCREEN + 19 * 40,x
    sta SCREEN + 20 * 40,x
    lda drawColumn
    jsr readNearColumn
    ldx drawColumn
    .for (var row = 0; row < 4; row++) {
        lda columnData + row
        sta SCREEN + (21 + row) * 40,x
    }
    inc drawColumn
    lda drawColumn
    cmp #40
    beq columnsReady
    jmp initializeColumns
columnsReady:
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

    // The bitmap sky owns Color RAM rows 0-11; the world retains rows 12-24.
    ldx #0
copySkyColors:
    lda skyColors,x
    sta $d800,x
    inx
    bne copySkyColors
    ldx #0
copySkyColorTail:
    lda skyColors+$100,x
    sta $d900,x
    inx
    cpx #SKY_CELLS-$100
    bne copySkyColorTail

    // Keep the loadable PRG below I/O. Only startup copies phase B to high RAM.
    ldx #0
copySkyBitmapB:
    .for (var page = 0; page < SKY_BITMAP_BYTES / $100; page++) {
        lda skyBitmapBStaged + page * $100,x
        sta skyBitmapB + page * $100,x
    }
    inx
    bne copySkyBitmapB

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
    lda #$0b
    sta $d011
    NextIRQ(40, irqHeader)
    lda #1
    sta skyPhase
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
mainComplete:
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
    // The static MCI sky keeps alternating even while world motion is paused.
    lda skyPhase
    eor #1
    sta skyPhase
    tax
    lda skyBankValues,x
    sta $dd00
    lda #$38
    sta $d018
    lda skyScrollValues,x
    sta $d016
    lda skyBackground
    sta $d021
    lda #$3b
    sta $d011
    lda #0
    sta $d01b
    lda #14
    sta $d022
    lda #3
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
    NextIRQ(146, irqFar)
    jmp irqReturn

irqFar:
    // Main is waiting on farDone here, so IRQ latency comes from its short polling loop.
    // Preload values, then change banks after the last sky fetch and before badline 147.
    lda fineBack
    ora #$10
    tax
    ldy #$1b
    lda worldBankValue
    .for (var delay = 0; delay < 5; delay++) {
        nop
    }
skyWorldBankSwitch:
    sta $dd00
    lda #$02
    sta $d018
    stx $d016
skyWorldModeSwitch:
    sty $d011
worldDisplayReady:
    NextIRQ(178, irqMiddle)
    jmp irqReturn

irqMiddle:
    // The original transition masks the bottom of the 12-row background map.
    // Its color mask also hides the charset/fine-scroll change at raster 186.
    WaitPastRaster(180)
    lda #1
    sta $d023
    WaitPastRaster(183)
    lda #$04
    sta $d021
    sta $d022
    sta $d023
    WaitPastRaster(185)
    lda #$04
    sta $d018
    lda fineMiddle
    ora #$10
    sta $d016
    WaitPastRaster(186)
    lda #14
    sta $d022
    lda #11
    sta $d023
    lda #1
    sta farDone
    NextIRQ(198, irqRoadPalette)
    jmp irqReturn

irqRoadPalette:
    WaitPastRaster(201)
    lda #11
    sta $d021
    WaitPastRaster(202)
    lda #$10
    sta $d016
    lda #1
    sta middleDone
    NextIRQ(218, irqNear)
    jmp irqReturn

irqNear:
    lda fineNear
    ora #$10
    sta $d016
irqNearPalette:
    lda #0
    sta $d022
    lda #3
    sta $d023
    lda #$7f
    sta $d01b                       // The frontmost ground can cover the actor's feet.
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
    AdvanceBand(5, 12, coarseBack, fineBack, 2, BACK_COLUMNS, readBackColumn)
    rts

updateMiddle:
    lda paused
    beq !advance+
    rts
!advance:
    AdvanceBand(17, 2, coarseMiddle, fineMiddle, 4, MIDDLE_COLUMNS, readMiddleColumn)
    rts

updateNear:
    lda paused
    beq !advance+
    rts
!advance:
    AdvanceBand(21, 4, coarseNear, fineNear, 6, NEAR_COLUMNS, readNearColumn)
    rts

readBackColumn:
    tax
    .for (var row = 0; row < 12; row++) {
        lda nativeBackMap + row * BACK_COLUMNS,x
        sta columnData + row
    }
    rts

readMiddleColumn:
    ExpandMetatileColumn(nativeMiddleIds, middleDefLow, middleDefHigh, 2)
    rts

readNearColumn:
    ExpandMetatileColumn(nativeNearIds, nearDefLow, nearDefHigh, 4)
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
skyPhase:
    .byte 1
skyBankValues:
    .byte 1, 0
skyScrollValues:
    .byte $18, $19
worldBankValue:
    .byte 2
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
drawColumn:
    .byte 0
sourceColumn:
    .byte 0
columnData:
    .fill 12, 0
worldColumnPeriods:
    .byte BACK_COLUMNS, MIDDLE_COLUMNS, NEAR_COLUMNS

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

.macro WaitPastRaster(line) {
    lda #line
!wait:
    cmp $d012
    bcs !wait-
}

.macro AdvanceBand(firstRow, rows, coarse, fine, pixels, columns, reader) {
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
    cmp #columns
    bcc !valid+
    lda #0
    sta coarse
!valid:
    // Shift only the visible codes; the new edge is decoded from the native map format.
    ldx #0
!shift:
    .for (var row = 0; row < rows; row++) {
        lda SCREEN + (firstRow + row) * 40 + 1,x
        sta SCREEN + (firstRow + row) * 40,x
    }
    inx
    cpx #39
    bne !shift-

    lda coarse
    clc
    adc #39
    cmp #columns
    bcc !column+
    sec
    sbc #columns
!column:
    sta sourceColumn
    jsr reader
    .for (var row = 0; row < rows; row++) {
        lda columnData + row
        sta SCREEN + (firstRow + row) * 40 + 39
    }
!done:
}

.macro ExpandMetatileColumn(ids, definitionLow, definitionHigh, rows) {
    // A character column selects one of four columns within the referenced metatile.
    pha
    and #3
    tay
    pla
    lsr
    lsr
    tax
    lda ids,x
    tax
    lda definitionLow,x
    sta TILE_POINTER
    lda definitionHigh,x
    sta TILE_POINTER+1
    .for (var row = 0; row < rows; row++) {
        lda (TILE_POINTER),y
        sta columnData + row
        .if (row < rows - 1) {
            iny
            iny
            iny
            iny
        }
    }
}

#import "rimrunner-parallax-assets.asm"
