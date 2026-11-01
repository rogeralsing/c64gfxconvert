// PAL C64 starter: a screen title and six raster color bands.
// Raster polling keeps this example small; it is not a cycle-stable IRQ routine.

BasicUpstart2(start)

start:
    sei
    lda #0
    sta $d020
    sta $d021

    ldx #0
clearScreen:
    lda #$20
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    lda #1
    sta $d800,x
    sta $d900,x
    sta $da00,x
    sta $db00,x
    inx
    bne clearScreen

    ldx #0
writeTitle:
    lda title,x
    beq frame
    sta $0400 + 3 * 40 + 10,x
    inx
    bne writeTitle

frame:
    // Wait for the high raster bit, then the start of the next PAL frame.
    bit $d011
    bpl frame
waitFrameStart:
    bit $d011
    bmi waitFrameStart

    RasterBar($60, 6)
    RasterBar($78, 14)
    RasterBar($90, 3)
    RasterBar($a8, 13)
    RasterBar($c0, 7)
    RasterBar($d8, 2)
    RasterBar($f0, 0)
    jmp frame

title:
    .encoding "screencode_mixed"
    .text "c64 toolchain ready"
    .byte 0

.macro RasterBar(line, color) {
!wait:
    lda $d012
    cmp #line
    bne !wait-
    lda #color
    sta $d020
    sta $d021
}
