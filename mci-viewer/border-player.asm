// Standalone PAL MCI border experiment. The original two bitmap fields remain
// intact; multiplexed hires checker sprites occupy the opened overscan area.
.var image = LoadBinary("image.mci")
.var fullRowX = List().add(48, 96, 144, 0, 336, 192, 240, 288)

.macro waitCycles(cycles) {
    .assert "Delay is representable", cycles == 0 || cycles >= 2, true
    .if ((cycles & 1) != 0) {
        bit $00
        .fill (cycles - 3) / 2, $ea
    } else {
        .fill cycles / 2, $ea
    }
}

.macro setSideY(value) {
    ldy #value
    sty $d007
    sty $d009
}

.macro setAllY(value) {
    ldy #value
    .for (var sprite = 0; sprite < 8; sprite++) {
        sty $d001 + sprite * 2
    }
}

.function checkerByte(offset) {
    // Fill every displayed row so adjacent multiplexed tiles meet without gaps.
    .return offset >= 63 ? 0 : (floor(offset / 3) & 1) == 0 ? $aa : $55
}

.function lastSideByte(offset) {
    // Spare slots start ten lines early, underneath the preceding side strip.
    .return offset < 30 ? 0 : checkerByte(offset)
}

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
    sta $d01b
    sta $d01c
    sta phase
    sta fieldCounter
    sta $7fff
    sta $bfff
    sta $d020
    lda #$0b
    sta $d011
    lda #$0f
    sta $d019
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda $dd02
    ora #3
    sta $dd02

    ldx #0
!colors:
    .for (var page = 0; page < 4; page++) {
        lda sharedColors + page * $100,x
        sta $d800 + page * $100,x
    }
    inx
    bne !colors-
    lda background
    sta $d021
    lda #$08
    sta $d018
    lda #$18
    sta $d016
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    .for (var sprite = 0; sprite < 8; sprite++) {
        lda #<fullRowX.get(sprite)
        sta $d000 + sprite * 2
        lda #8
        sta $d001 + sprite * 2
        lda #3
        sta $d027 + sprite
    }
    lda #$90
    sta $d010
    lda #$ff
    sta $d017
    sta $d01d
    sta $d015
    lda #<irqFirst
    sta $fffe
    lda #>irqFirst
    sta $ffff
    lda #44
    sta $d012
    // Bit 7 keeps the raster IRQ at 300/301 while the display uses bitmap mode.
    lda #$bb
    sta $d011
    lda #1
    sta $d01a
    cli
idle:
    jmp idle

irqFirst:
    pha
    txa
    pha
    tya
    pha
    lda #<irqStable
    sta $fffe
    lda #>irqStable
    sta $ffff
    inc $d012
    lda #1
    sta $d019
    tsx
    cli
    .fill 8, $ea

.align $100
irqStable:
    txs
    ldx #8
!delay:
    dex
    bne !delay-
    bit $00
    lda $d012
    cmp $d012
    beq * + 2

frameComplete:
    // The double IRQ is calibrated at PAL raster 302, cycle 4 (VICE CYC 3).
    // At this point phase identifies the completed picture.
    inc fieldCounter
    lda #<irqFirst
    sta $fffe
    lda #>irqFirst
    sta $ffff
    lda #44
    sta $d012
    lda #$bb
    sta $d011
    lda #1
    sta $d019
    lda phase
    eor #1
    sta phase
    tay
    lda $dd00
    and #$fc
    ora bankBits,y
    sta $dd00
    lda wideValues,y
    tax
    lda narrowValues,y
    stx $d016

    // The prefix is 76 cycles: next opcode is raster 303 cycle 17.
    // No sprites run in this interval until all eight start DMA at 8:55.
    :waitCycles(1105)
firstBorderStrobe:
    asl $d016

    .for (var raster = 9; raster <= 292; raster++) {
        .if (raster <= 49 || raster >= 251) {
            // Eight sprite DMAs: the previous read waits until cycle 11.
            stx $d016                         // Wide again at cycle 14.
            .if (raster == 40) {
                :setSideY(50)                 // 10 cycles.
                :waitCycles(26)
            } else .if (raster == 251) {
                ldy #240
                sty $d00c                     // Restore slot 6 before its new X match.
                ldy #$90
                sty $d010
                ldy #$ff
                sty $d01d
                ldy #80                       // Move after the last bitmap line.
                sty $d008                     // Sprite 4 returns to X=336.
                :waitCycles(12)
            } else .if (raster == 280) {
                :setAllY(8)                   // 34 cycles.
                :waitCycles(2)
            } else {
                :waitCycles(36)
            }
            // RMW writes on 55/56 survive sprite 0's BA warning at 55.
            asl $d016
        } else .if (raster == 50) {
            // Keep the right slot wide for the full final top-border row.
            stx $d016                         // Starts at cycle 11.
            ldy #$f7
            sty $d01d
            ldy #$e7
            sty $d017                         // Side sprites now use normal height.
            ldy #88                           // Sprite 4: X=344, high bit stays set.
            :waitCycles(24)
            sta $d016                         // Narrow at cycle 56.
            sty $d008                         // After the old X=336 match.
        } else .if (raster == 51) {
            stx $d016                         // Restore at cycle 8 before comparisons.
            // Y is 88: $cfbe,Y addresses $d016. Its dummy read at cycle 12
            // waits through the badline, leaving the required write at 56.
            sta $cfbe,y
            stx $d016                         // Wide at cycle 60.
        } else .if (raster == 250) {
            // The spare pair's normal-height DMA ends at cycle 16. Its first
            // ten rows were transparent; the last eleven finish the side.
            ldy #$ff
            sty $d017                         // Normal-height advance is already set.
            ldy #$bf
            sty $d01d
            ldy #192
            sty $d00a                         // Restore slot 5 after its left pixels.
            ldy #$10
            sty screenA + $3fd
            sty screenA + $3fe
            sty screenB + $3fd
            sty screenB + $3fe
            :waitCycles(6)
            asl $d016                         // Eight DMAs begin at cycle 55.
        } else .if (raster >= 230 && raster <= 249) {
            // Slots 5/6 extend the early DMA block: the CPU resumes at 9.
            .if ((raster & 7) == 3) {
                // Y stays 88: the indexed dummy read waits from 12 through 55.
                sta $cfbe,y
            } else {
                .if (raster == 240) {
                    :setAllY(250)
                    ldy #88
                    :waitCycles(8)
                } else .if (raster == 248) {
                    ldy #$b3
                    sty $d011
                    ldy #88
                    :waitCycles(36)
                } else {
                    :waitCycles(44)
                }
                sta $d016                     // Narrow at cycle 56.
            }
            stx $d016                         // Wide at cycle 60.
            .if (raster >= 239) {
                // Slots 3/4 have finished. Use the four free cycles before
                // slots 5/6 assert BA, so the next row still resumes at 9.
                :waitCycles(4)
            }
        } else {
            // Only sprite 3/4 DMA: the next opcode resumes at cycle 5.
            .if ((raster & 7) == 3) {
                // Operand read 12 waits through the badline, then writes 56.
                :waitCycles(5)
            } else .if (raster == 52) {
                // Finish the right width change after the transition badline.
                ldy #$e7
                sty $d01d
                :waitCycles(42)
            } else .if (raster == 69 || raster == 90 || raster == 111 || raster == 132 || raster == 153 || raster == 174 || raster == 216) {
                :setSideY(raster + 2)
                :waitCycles(38)
            } else .if (raster == 194) {
                :setSideY(197)                 // Avoid the badline at 195.
                :waitCycles(38)
            } else .if (raster == 220) {
                ldy #$11
                sty screenA + $3fd
                sty screenA + $3fe
                sty screenB + $3fd
                sty screenB + $3fe
                ldy #0
                sty $d00a
                ldy #88
                sty $d00c
                ldy #$d0
                sty $d010
                ldy #$87
                sty $d01d
                sty $d017
                :waitCycles(2)
            } else .if (raster == 222) {
                ldy #229
                sty $d00b
                sty $d00d
                ldy #88                       // Retain this through both badlines.
                :waitCycles(36)
            } else {
                :waitCycles(48)
            }
            sta $d016                         // Narrow at cycle 56.
            stx $d016                         // Wide at cycle 60.
        }
    }

    // The last expanded row ends at 292:16, so this restore does not stall.
    stx $d016
    pla
    tay
    pla
    tax
    pla
    rti

nmi:
    rti
.align 8
bankBits: .byte 2, 1
wideValues: .byte $18, $19
narrowValues: .byte $10, $11
phase: .byte 0
fieldCounter: .byte 0
.assert "Raster kernel avoids staged colors", * <= $3000, true

* = $3000 "Shared color RAM"
sharedColors:
    .fill 1000, image.get(18434 + i)
    .fill 24, 0
background:
    .byte image.get(1002)

* = $4000 "Phase A screen"
screenA:
    .fill 1000, image.get(2 + i)
    .fill 16, 0
    .fill 8, $10
* = $4400 "Phase A checker sprite"
spriteChecker:
    .fill 64, checkerByte(i)
spriteLastSide:
    .fill 64, lastSideByte(i)
* = $6000 "Phase A bitmap"
bitmapA:
    .fill 8000, image.get(1026 + i)

* = $8000 "Phase B screen"
screenB:
    .fill 1000, image.get(17410 + i)
    .fill 16, 0
    .fill 8, $10
* = $8400 "Phase B checker sprite"
    .fill 64, checkerByte(i)
    .fill 64, lastSideByte(i)
* = $a000 "Phase B bitmap"
bitmapB:
    .fill 8000, image.get(9218 + i)
