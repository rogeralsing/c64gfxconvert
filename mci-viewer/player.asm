// Standalone PAL MCI display: one multicolor bitmap per video frame.
// The builder stages the original, uncompressed True Paint file as image.mci.
.var image = LoadBinary("image.mci")

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
    sta phase
    lda #$0f
    sta $d019
    lda #$0b
    sta $d011

    // RESTORE remains harmless while the KERNAL ROM is switched out.
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda $dd02
    ora #3
    sta $dd02

    ldx #0
copyColors:
    lda sharedColors,x
    sta $d800,x
    lda sharedColors+$100,x
    sta $d900,x
    lda sharedColors+$200,x
    sta $da00,x
    lda sharedColors+$300,x
    sta $db00,x
    inx
    bne copyColors

    lda background
    sta $d020
    sta $d021
    lda #$08
    sta $d018
    lda #$18
    sta $d016
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    lda #$3b
    sta $d011

waitFrame:
    // Raster 256 is below all 200 picture lines on a PAL C64.
    bit $d011
    bpl waitFrame
frameComplete:
    // At this label, phase identifies the picture just fully displayed.
    lda phase
    eor #1
    sta phase
    tax
    lda $dd00
    and #$fc
    ora bankBits,x
    sta $dd00
    lda scrollValues,x
    sta $d016
waitFrameStart:
    bit $d011
    bmi waitFrameStart
    jmp waitFrame

nmi:
    rti
phase:
    .byte 0
bankBits:
    .byte 2, 1
scrollValues:
    .byte $18, $19

.assert "Player must not overlap color data", * < $2000, true

* = $2000 "Shared color RAM"
sharedColors:
    .fill 1000, image.get(18434 + i)
    .fill 24, 0
background:
    .byte image.get(1002)

* = $4000 "Phase A screen"
screenA:
    .fill 1000, image.get(2 + i)
    .fill 24, 0
* = $6000 "Phase A bitmap"
bitmapA:
    .fill 8000, image.get(1026 + i)

* = $8000 "Phase B screen"
screenB:
    .fill 1000, image.get(17410 + i)
    .fill 24, 0
* = $a000 "Phase B bitmap"
bitmapB:
    .fill 8000, image.get(9218 + i)
