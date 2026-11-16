// PAL MCI with the converter's exact two-field, normal-height side sprites.
// The upper/lower overscan contains no sprite assets and stays black.
.var image = LoadBinary("image.mci")
.var sprites = LoadBinary("sprites.bin")
#import "border-settings.asm"

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

.macro setBandPointers(band, tail) {
    ldy #$10 + band
    .if (tail) {
        sty screenTailA + $3fb
        sty screenTailB + $3fb
    } else {
        sty screenA + $3fb
        sty screenB + $3fb
    }
    ldy #$1a + band
    .if (tail) {
        sty screenTailA + $3fc
        sty screenTailB + $3fc
    } else {
        sty screenA + $3fc
        sty screenB + $3fc
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
    sta $d017
    sta $d01d
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
    lda #BORDER_SHARED_1
    sta $d025
    lda #BORDER_SHARED_2
    sta $d026
    lda #BORDER_SPRITE_COLOR
    sta $d02a
    sta $d02b
    sta $d02c
    sta $d02d
    lda #BORDER_MULTICOLOR_MASK
    sta $d01c
    lda #$50
    sta $d010
    lda #229
    sta $d00b
    sta $d00d
    lda #$78
    sta $d015
    lda #$08
    sta $d018
    lda #$18
    sta $d016
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    lda #<irqFirst
    sta $fffe
    lda #>irqFirst
    sta $ffff
    lda #44
    sta $d012
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
    // phase identifies the completed field; next-field preparation follows.
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
    tya
    sta $d006
    sta $d00a
    clc
    adc #88
    sta $d008
    sta $d00c
    lda #$08
    sta $d018
    :setBandPointers(0, false)
    :setBandPointers(5, true)
    ldy phase
    lda wideValues,y
    tax
    lda narrowValues,y
    stx $d016
    ldy #88

    // Do not set Y=50 until after raster 306 (its low byte is also 50).
    // Otherwise the VIC starts an unwanted sprite DMA above the picture.
    // Preparation takes 150 cycles, ending at raster 304 cycle 28.
    :waitCycles(162)
    :setSideY(50)
    ldy #88
    :waitCycles(3505)
firstBorderStrobe:
    sta $d016
    stx $d016

    .for (var raster = 51; raster <= 250; raster++) {
        .if (raster >= 230) {
            // The spare pair extends the early DMA block through cycle 8.
            .if ((raster & 7) == 3) {
                sta $cfbe,y
            } else {
                .if (raster == 248) {
                    // Keep only invisible black overscan above/below the art.
                    ldy #$b3
                    sty $d011
                    ldy #88
                    :waitCycles(36)
                } else {
                    :waitCycles(44)
                }
                sta $d016
            }
            stx $d016
            .if (raster >= 239 && raster <= 249) {
                // Once slots 3/4 finish, consume the four cycles before 5/6 BA.
                :waitCycles(4)
            }
        } else .if (raster == 155) {
            // This band boundary is a badline. Switching an identical screen
            // changes both sprite pointers with one register write.
            sty $d018
            sta $cfde,y                       // Y=$38; dummy read waits at 12.
            stx $d016
        } else {
            .if ((raster & 7) == 3) {
                :waitCycles(5)
            } else .if (raster == 69 || raster == 90 || raster == 111 || raster == 132 || raster == 153 || raster == 174 || raster == 216) {
                :setSideY(raster + 2)
                ldy #88
                :waitCycles(36)
            } else .if (raster == 194) {
                :setSideY(197)
                ldy #88
                :waitCycles(36)
            } else .if (raster == 71 || raster == 92 || raster == 113 || raster == 134 || raster == 176 || raster == 197 || raster == 218) {
                .var band = (raster - 50) / 21
                :setBandPointers(band, raster > 155)
                ldy #88
                :waitCycles(26)
            } else .if (raster == 154) {
                ldy #$38
                :waitCycles(46)
            } else .if (raster == 156) {
                ldy #88
                :waitCycles(46)
            } else {
                :waitCycles(48)
            }
            sta $d016
            stx $d016
        }
    }
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
    .byte 0, 0, 0, $10, $1a, $19, $23, 0
* = $4400 "Phase A exported sprites"
spriteDataA:
    .fill 1280, sprites.get(i)
* = $4c00 "Phase A pointer-tail screen"
screenTailA:
    .fill 1000, image.get(2 + i)
    .fill 16, 0
    .byte 0, 0, 0, $15, $1f, $19, $23, 0
* = $6000 "Phase A bitmap"
bitmapA:
    .fill 8000, image.get(1026 + i)

* = $8000 "Phase B screen"
screenB:
    .fill 1000, image.get(17410 + i)
    .fill 16, 0
    .byte 0, 0, 0, $10, $1a, $19, $23, 0
* = $8400 "Phase B exported sprites"
spriteDataB:
    .fill 1280, sprites.get(1280 + i)
* = $8c00 "Phase B pointer-tail screen"
screenTailB:
    .fill 1000, image.get(17410 + i)
    .fill 16, 0
    .byte 0, 0, 0, $15, $1f, $19, $23, 0
* = $a000 "Phase B bitmap"
bitmapB:
    .fill 8000, image.get(9218 + i)
