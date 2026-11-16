// Standalone Batman MCI picture with the converter's original border assets.
// All 104 multicolor sprite frames and both bitmap fields are kept unchanged.
.var image = LoadBinary("image.mci")
.var bankA = LoadBinary("bank-a.bin")
.var bankB = LoadBinary("bank-b.bin")
#import "settings.asm"
.label screenA = $4000
.label screenB = $c000
.label screenTailA = $4400
.label screenTailB = $c400
.label screenBottomA = $5800
.label screenBottomB = $d800
.label screenSecondA = $5c00
.label screenSecondB = $dc00
.label spriteDataA = $4800
.label spriteDataB = $c800
.label bitmapA = $6000
.label bitmapB = $e000
.label sideLeftSlot = 1
.label sideRightSlot = 2
.label finalSideLeftSlot = 3
.label finalSideRightSlot = 4
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
    sty $d003
    sty $d005
}

.macro setAllY(value) {
    ldy #value
    .for (var sprite = 0; sprite < 8; sprite++) {
        sty $d001 + sprite * 2
    }
}

.macro setBandPointers(band, tail) {
    ldy #$40 + band
    sty (tail ? screenTailA : screenA) + $3f9
    sty (tail ? screenTailB : screenB) + $3f9
    ldy #$4a + band
    sty (tail ? screenTailA : screenA) + $3fa
    sty (tail ? screenTailB : screenB) + $3fa
}

.macro setPrimaryRow(first, last, offset) {
    .for (var slot = first; slot <= last; slot++) {
        .var column = List().add(1, 2, 3, 0, 7, 4, 5, 6).get(slot)
        ldy #$20 + offset + column
        sty screenA + $3f8 + slot
        sty screenB + $3f8 + slot
    }
}

.macro paintRow(raster) {
        .if (raster <= 49 || raster >= 251) {
            // Eight sprite DMAs: the previous read waits until cycle 11.
            stx $d016                         // Wide again at cycle 14.
            .if (raster == 20 || raster == 260) {
                // Prepare the next normal-height Y match while DMA is active.
                :setAllY(raster == 20 ? 29 : 15)
                :waitCycles(2)
            } else .if (raster == 29 || raster == 271) {
                // All eight final old-row fetches finished by cycle 10.
                // Select their second-band pointers before the next fetch.
                ldy #(raster == 29 ? $78 : $68)
                sty $d018
                :waitCycles(30)
            } else .if (raster == 40) {
                :setSideY(50)                 // 10 cycles.
                :setBandPointers(0, false)    // The second top matrix is active.
                :waitCycles(6)
            } else .if (raster == 251) {
                ldy bottomSixXs,x
                sty $d00c                     // Restore slot 6 before its new X match.
                ldy #$90
                sty $d010
                ldy #$ff
                sty $d01d
                ldy bottomFourXs,x             // Move after the last bitmap line.
                sty $d008                     // Sprite 4 returns to X=336.
                :waitCycles(8)
            } else .if (raster == 280) {
                :setAllY(8)                   // 34 cycles.
                :waitCycles(2)
            } else {
                :waitCycles(36)
            }
            // RMW writes on 55/56 survive sprite 0's BA warning at 55.
            asl $d016
        } else .if (raster == 50) {
            // Slots 1/2 have finished their last top-row pixels before their
            // width changes; far-right top slot 4 retains its full width.
            stx $d016                         // Wide at cycle 14.
            ldy #$08
            sty $d018
            ldy leftXs,x
            :waitCycles(4)
            sty $d002                         // Left side moves to slot 1.
            stx $d004                         // X=$58/$59; right side uses slot 2.
            ldy #$94
            sty $d010
            ldy #$f9
            sty $d01d
            ldy #88
            :waitCycles(2)
            sta $d016                         // Narrow at cycle 56.
            stx $d016                         // BA delays this until next row cycle 4.
        } else .if (raster == 155) {
            sty $d018                         // Prepared side band five at $4400/$c400.
            sta $cffe,y                       // Y=$18; dummy read waits at cycle 12.
            stx $d016
        } else .if (raster == 250) {
            // The spare pair's normal-height DMA ends at cycle 16. Its first
            // ten rows were transparent; the last eleven finish the side.
            ldy #$08
            sty $d018                         // Prepared first lower-band pointers.
            ldy #$bf
            sty $d01d
            ldy bottomFiveXs,x
            sty $d00a                         // Restore slot 5 after its left pixels.
            :waitCycles(22)
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
                } else .if (raster == 241) {
                    // Both primary sides ended on raster 239. Restore their
                    // full-row X coordinates before the bottom starts.
                    ldy restoreOneXs,x
                    sty $d002
                    ldy restoreTwoXs,x
                    sty $d004
                    ldy bottomFourXs,x
                    sty $d008
                    ldy #$d0
                    sty $d010
                    ldy #88                       // Retain the D016 indexed address.
                    :waitCycles(12)
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
            // Sprite 1/2 DMA carries the wide write to the next row, ending at 4.
            .if ((raster & 7) == 3) {
                // Operand read 12 waits through the badline, then writes 56.
                :waitCycles(5)
            } else .if (raster == 52) {
                // Restore the indexed badline address after the transition row.
                ldy #88
                :waitCycles(46)
            } else .if (raster == 160 || raster == 161) {
                :setPrimaryRow(raster == 160 ? 0 : 4, raster == 160 ? 3 : 7, 16)
                :waitCycles(8)
            } else .if (raster == 154) {
                ldy #$18
                :waitCycles(46)
            } else .if (raster == 156) {
                ldy #88
                :waitCycles(46)
            } else .if (raster == 71 || raster == 92 || raster == 113 || raster == 134 || raster == 176 || raster == 197 || raster == 218) {
                .var band = (raster - 50) / 21
                .if (raster == 218) {
                    ldy #$48
                    sty screenTailA + $3fb
                    sty screenTailB + $3fb
                    ldy #$52
                    sty screenTailA + $3fc
                    sty screenTailB + $3fc
                } else {
                    :setBandPointers(band, raster > 155)
                }
                :waitCycles(28)
            } else .if (raster == 69 || raster == 90 || raster == 111 || raster == 132 || raster == 153 || raster == 174 || raster == 216) {
                .if (raster == 216) {
                    // Move the final primary band to early-DMA slots 3/4 so
                    // spare slots 5/6 cannot delay the next wide write.
                    ldy #218
                    sty $d007
                    sty $d009
                } else {
                    :setSideY(raster + 2)
                }
                :waitCycles(38)
            } else .if (raster == 194) {
                :setSideY(197)                 // Avoid the badline at 195.
                :waitCycles(38)
            } else .if (raster == 210) {
                ldy sideXs,x
                sty $d008
                ldy #$e1
                sty $d01d
                :waitCycles(34)
            } else .if (raster == 220) {
                ldy leftXs,x
                sty $d00a
                ldy sideXs,x
                sty $d00c
                ldy #$d0
                sty $d010
                ldy #$87
                sty $d01d
                :waitCycles(20)
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
    sta phase
    sta fieldCounter
    sta $7fff
    sta $ffff
    sta $d020
    lda #$0b
    sta $d011
    lda #$0f
    sta $d019
    // The IRQ high byte shares bank 3's idle graphics byte. Zero-page
    // trampolines keep it zero, including during the stabilizing interrupt.
    lda #$34
    sta $01
    ldx #0
!relocate:
    .for (var page = 0; page < 64; page++) {
        lda $8000 + page * $100,x
        sta $c000 + page * $100,x
    }
    inx
    beq !relocated+
    jmp !relocate-
!relocated:
    lda #$35
    sta $01
    lda #$4c
    sta $c0
    sta $c3
    lda #<irqFirst
    sta $c1
    lda #>irqFirst
    sta $c2
    lda #<irqStable
    sta $c4
    lda #>irqStable
    sta $c5
    lda #$40
    sta $c6
    lda #$c6
    sta $fffa
    lda #0
    sta $fffb
    sta $ffff
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
    lda #SPRITE_SHARED_1
    sta $d025
    lda #SPRITE_SHARED_2
    sta $d026
    lda #$ff
    sta $d01c
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
        lda #SPRITE_COLOR
        sta $d027 + sprite
    }
    lda #$90
    sta $d010
    lda #0
    sta $d017
    lda #$ff
    sta $d01d
    sta $d015
    lda #$c0
    sta $fffe
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
    lda #$c3
    sta $fffe
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
    // The zero-page trampoline supplies the removed three delay cycles.
    lda $d012
    cmp $d012
    beq * + 2

frameComplete:
    // The double IRQ is calibrated at PAL raster 302, cycle 4 (VICE CYC 3).
    // At this point phase identifies the completed picture.
    inc fieldCounter
    lda #$c0
    sta $fffe
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
    .for (var slot = 0; slot < 8; slot++) {
        lda fullX + slot * 2,y
        sta $d000 + slot * 2
    }
    ldy #$90
    sty $d010
    ldy #$ff
    sty $d01d
    ldy #$08
    sty $d018
    :setPrimaryRow(0, 7, 0)
    :setBandPointers(5, true)
    ldy phase
    lda wideValues,y
    tax
    lda narrowValues,y
    stx $d016

    // Phase preparation runs entirely below the picture, with no sprite DMA.
    :waitCycles(913)
firstBorderStrobe:
    asl $d016

    .for (var raster = 9; raster <= 50; raster++) {
        :paintRow(raster)
    }
    // Sprite slots 1/2 leave cycles 55/56 free even on a badline. Their late
    // DMA delays the preceding wide write until cycle 4; this row resumes at 5.
    stx $d016
firstSideIndexed:
    sta $cfbe,y
    stx $d016
    .for (var raster = 52; raster <= 292; raster++) {
        :paintRow(raster)
    }

    // The last normal row ends at 292:16, so this restore does not stall.
    stx $d016
    ldy #$08
    sty $d018
    pla
    tay
    pla
    tax
    pla
    rti

nmi:
    rti
.align 8
bankBits: .byte 2, 0
fullX:
    .for (var slot = 0; slot < 8; slot++) {
        .byte <fullRowX.get(slot), <(fullRowX.get(slot) + 1)
    }
sideXValues: .byte 88, 89
.label sideXs = sideXValues - $58
leftXValues: .byte 0, 1
.label leftXs = leftXValues - $58
restoreOneValues: .byte 96, 97
.label restoreOneXs = restoreOneValues - $58
restoreTwoValues: .byte 144, 145
.label restoreTwoXs = restoreTwoValues - $58
bottomFourValues: .byte 80, 81
.label bottomFourXs = bottomFourValues - $58
bottomFiveValues: .byte 192, 193
.label bottomFiveXs = bottomFiveValues - $58
bottomSixValues: .byte 240, 241
.label bottomSixXs = bottomSixValues - $58
wideValues: .byte $58, $59
narrowValues: .byte $10, $11
.assert "Phase-indexed X aliases stay within their timing page", floor(sideXs / $100) == floor((sideXs + $59) / $100) && floor(bottomSixXs / $100) == floor((bottomSixXs + $59) / $100), true
phase: .byte 0
fieldCounter: .byte 0
.assert "Raster kernel avoids staged colors", * <= $3000, true

* = $3000 "Shared color RAM"
sharedColors:
    .fill 1000, image.get(18434 + i)
    .fill 24, 0
background:
    .byte image.get(1002)

* = $4000 "Phase A VIC bank"
    .fill $4000, bankA.get(i)
* = $8000 "Phase B VIC bank staging"
    .fill $4000, bankB.get(i)
