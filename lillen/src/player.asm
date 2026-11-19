// Standalone Lillen MCI picture, adapted from the Batman raster kernel.
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
// Vertical sprites are all 24 pixels wide. The phase index is $58/$59
// during the raster kernel, allowing an eight-cycle X update.
.macro setX(table, slot) {
    ldy table + slot * 2,x
    sty $d000 + slot * 2
}

.macro phaseXTable(positions) {
    .for (var slot = 0; slot < 8; slot++) {
        .byte <positions.get(slot), <(positions.get(slot) + 1)
    }
}

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

.macro setSpriteColor(slot, index) {
    ldy #spriteColors.get(index)
    sty $d027 + slot
}

.macro paintRow(raster) {
        .if (raster <= 49 || raster >= 251) {
            // Eight sprite DMAs: the previous read waits until cycle 11.
            stx $d016                         // Wide again at cycle 14.
            .if (raster == 12) {
                // These old slots are transparent in both fields.
                :setX(topSecondXs, 0)
                :setSpriteColor(0, 9)
                :setX(topSecondXs, 1)
                :setSpriteColor(1, 10)
                :waitCycles(8)
            } else .if (raster == 20 || raster == 260) {
                :setAllY(raster == 20 ? 29 : 15)
                :waitCycles(2)
            } else .if (raster == 29) {
                ldy #$78
                sty $d018
                :setX(topSecondXs, 2)
                :setX(topSecondXs, 5)
                :setSpriteColor(5, 12)
                :setX(topSecondXs, 6)
            } else .if (raster == 30) {
                :setX(topSecondXs, 7)
                :setSpriteColor(7, 14)
                :setSpriteColor(4, 15)
                :waitCycles(16)
            } else .if (raster == 31) {
                // The first incoming row of slot 4 is transparent.
                :setX(topSecondXs, 4)
                :waitCycles(28)
            } else .if (raster == 254) {
                :setX(bottomSecondXs, 0)
                :setSpriteColor(0, 25)
                :waitCycles(22)
            } else .if (raster == 270) {
                lda bottomSecondXs + 5 * 2,x
                :waitCycles(32)
            } else .if (raster == 271) {
                ldy #$68
                sty $d018
                :waitCycles(8)
                :setX(bottomSecondXs, 1)
                :setX(bottomSecondXs, 2)
                sta $d00a
                :waitCycles(2)
            } else .if (raster == 272) {
                :setX(bottomSecondXs, 6)
                ldy #$d0
                sty $d010
                :setX(bottomSecondXs, 7)
                :setSpriteColor(7, 30)
                :waitCycles(8)
            } else .if (raster == 273) {
                // The first incoming row of slot 4 is transparent.
                :setX(bottomSecondXs, 4)
                :waitCycles(28)
            } else .if (raster == 40) {
                :setSideY(50)                 // 10 cycles.
                :setBandPointers(0, false)    // The second top matrix is active.
                :waitCycles(6)
            } else .if (raster == 251) {
                // Slot 6's final side pixels finished on the previous row.
                sty $d02d
                :setX(bottomFirstXs, 6)                     // Restore slot 6 before its new X match.
                ldy #$90
                sty $d010
                :waitCycles(6)
                :setX(bottomFirstXs, 4)
                :waitCycles(4)
            } else .if (raster == 280) {
                :setAllY(8)                   // 34 cycles.
                :waitCycles(2)
            } else {
                :waitCycles(36)
            }
            // RMW writes on 55/56 survive sprite 0's BA warning at 55.
            asl $d016
        } else .if (raster == 50) {
            // Hand the two side slots over after their last upper-border
            // comparators. The late DMA schedule stays identical to Batman.
            stx $d016                         // Wide at cycle 14.
            ldy #$08
            sty $d018
            ldy leftXs,x
            sty $d002                         // Left side moves to slot 1.
            stx $d004                         // X=$58/$59; right side uses slot 2.
            ldy #$04
            sty $d010
            :setSpriteColor(2, 42)             // Old top slot 2 finished by cycle 38.
            :waitCycles(6)
            ldy #spriteColors.get(32)         // Carries the new left color into row 51.
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
            :waitCycles(6)
            :setX(bottomFirstXs, 5)                         // Restore slot 5 after its left pixels.
            :setSpriteColor(5, 20)
            ldy #spriteColors.get(21)         // Preload slot 6's first lower-row color.
            :waitCycles(14)
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
                    // Both primary sides ended on raster 239.
                    :setX(bottomFirstXs, 1)
                    :setX(bottomFirstXs, 2)
                    :setX(bottomFirstXs, 4)
                    ldy #$d0
                    sty $d010
                    ldy #88                       // Retain the D016 indexed address.
                    :waitCycles(12)
                } else .if (raster == 244) {
                    :setX(bottomFirstXs, 0)
                    :setX(bottomFirstXs, 7)
                    ldy #88
                    :waitCycles(26)
                } else .if (raster == 248) {
                    ldy #$b3
                    sty $d011
                    ldy #88
                    :waitCycles(36)
                } else .if (raster == 242) {
                    // These six slots are inactive; spare slots 5/6 still draw.
                    :setSpriteColor(3, 16)
                    :setSpriteColor(0, 17)
                    :setSpriteColor(1, 18)
                    :setSpriteColor(2, 19)
                    :setSpriteColor(7, 22)
                    :setSpriteColor(4, 23)
                    ldy #88
                    :waitCycles(6)
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
                // The preceding band boundary is a badline. Both colors fit
                // here before the left sprite starts at X=0.
                :setSpriteColor(1, 37)
                :setSpriteColor(2, 47)
                ldy #88
                :waitCycles(34)
            } else .if (raster == 72 || raster == 93 || raster == 114 || raster == 135 || raster == 177 || raster == 198) {
                .var band = (raster - 51) / 21
                :setSpriteColor(2, 42 + band)
                ldy #88
                :waitCycles(40)
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
                .if (raster != 218) {
                    :setSpriteColor(1, 32 + band)
                    :waitCycles(22)
                } else {
                    :waitCycles(28)
                }
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
                ldy #$14
                sty $d010
                :setSpriteColor(3, 40)
                :setSpriteColor(4, 50)
                :waitCycles(22)
            } else .if (raster == 220) {
                ldy leftXs,x
                sty $d00a
                ldy sideXs,x
                sty $d00c
                ldy #$d0
                sty $d010
                :waitCycles(6)
                :setSpriteColor(5, 41)
                :setSpriteColor(6, 51)
                :waitCycles(8)
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
        lda #<topFirstX.get(sprite)
        sta $d000 + sprite * 2
        lda #8
        sta $d001 + sprite * 2
        .var column = List().add(1, 2, 3, 0, 7, 4, 5, 6).get(sprite)
        lda #spriteColors.get(column)
        sta $d027 + sprite
    }
    lda #0
    sta $d010
    sta $d017
    sta $d01d
    lda #$ff
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
    ldy #0
    sty $d010
    sty $d01d
    ldy #$08
    sty $d018
    :setPrimaryRow(0, 7, 0)
    :setBandPointers(5, true)
    .for (var slot = 0; slot < 8; slot++) {
        .var column = List().add(1, 2, 3, 0, 7, 4, 5, 6).get(slot)
        :setSpriteColor(slot, column)
    }
    ldy phase
    lda wideValues,y
    tax
    lda narrowValues,y
    stx $d016

    // Phase preparation runs entirely below the picture, with no sprite DMA.
    :waitCycles(865)
firstBorderStrobe:
    asl $d016

    .for (var raster = 9; raster <= 49; raster++) {
        :paintRow(raster)
    }
row50:
    :paintRow(50)
    // Sprite slots 1/2 leave cycles 55/56 free even on a badline. Their late
    // DMA delays the preceding wide write until cycle 4; this row resumes at 5.
    sty $d028                          // Row 50 preloaded the new left sprite color.
firstSideIndexed:
    sta $d016 - spriteColors.get(32),y
    stx $d016
    .for (var raster = 52; raster <= 209; raster++) {
        :paintRow(raster)
    }
row210:
    :paintRow(210)
    .for (var raster = 211; raster <= 219; raster++) {
        :paintRow(raster)
    }
row220:
    :paintRow(220)
    .for (var raster = 221; raster <= 249; raster++) {
        :paintRow(raster)
    }
row250:
    :paintRow(250)
    .for (var raster = 251; raster <= 292; raster++) {
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
.align $100
bankBits: .byte 2, 0
fullX:
    :phaseXTable(topFirstX)
.align $100
    .fill $58, 0
.label topSecondXs = * - $58
    :phaseXTable(topSecondX)
.label bottomFirstXs = * - $58
    :phaseXTable(bottomFirstX)
.label bottomSecondXs = * - $58
    :phaseXTable(bottomSecondX)
.label sideXs = * - $58
    .byte 88, 89
.label leftXs = * - $58
    .byte 0, 1
wideValues: .byte $58, $59
narrowValues: .byte $10, $11
.assert "Phase-indexed X reads stay within their timing page", floor(topSecondXs / $100) == floor((* - 1) / $100), true
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
