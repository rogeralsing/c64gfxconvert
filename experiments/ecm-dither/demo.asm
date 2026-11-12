// A fixed 64-slot charset, four global background colors and per-cell foregrounds.
BasicUpstart2(start)

* = $1000 "ECM setup"
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
    lda #$0f
    sta $d019
    lda #$0b
    sta $d011
    lda #<interrupt_return
    sta $fffa
    sta $fffe
    lda #>interrupt_return
    sta $fffb
    sta $ffff

    // Bank zero, screen $0400 and custom charset $2000.
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #$18
    sta $d018
    lda #$08
    sta $d016

    ldx #0
!copy_pages:
    .for (var page = 0; page < 3; page++) {
        lda screen_data + page*$100,x
        sta $0400 + page*$100,x
        lda color_data + page*$100,x
        sta $d800 + page*$100,x
    }
    inx
    bne !copy_pages-
!copy_tail:
    lda screen_data+$300,x
    sta $0700,x
    lda color_data+$300,x
    sta $db00,x
    inx
    cpx #232
    bne !copy_tail-

    // Screen-code bits 7..6 select these four registers.
    lda #1
    sta $d022
    lda #6
    sta $d023
    lda #14
    sta $d024
    lda #$5b
    sta $d011
ready:
    jmp ready

interrupt_return:
    rti

.assert "Runtime fits below charset", * < $2000, true

* = $2000 "ECM charset"
font:
    .import binary "build/font.bin"
.assert "ECM charset has exactly 64 slots", * - font, 512

* = $3000 "Screen codes"
screen_data:
    .import binary "build/screen.bin"
.assert "Screen contains 40x25 cells", * - screen_data, 1000

* = $3400 "Foreground colors"
color_data:
    .import binary "build/color.bin"
.assert "Colors contain 40x25 cells", * - color_data, 1000
