// Two copies of one cleaned cube reverse the leading and trailing masks.
// One forward six-stage contrast wave advances through trailing, core, and
// leading strips; the phase wraps without traversing the sequence backward.
.const SCREEN = $0400
.const FONT = $2000
.const SCREEN_SOURCE = $3000
.const FRAMES_PER_COLOR = 4
.const PHASE_COUNT = 6

BasicUpstart2(start)

* = $1000 "Cube illusion preview"
start:
    sei
    cld
    lda #$2f
    sta $00
    lda #$35
    sta $01

    // Mask both CIA interrupt sources; this preview does not use the KERNAL.
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $dd0e
    sta $dd0f
    sta $d01a
    sta $d015
    sta phase
    sta color_ticks
    lda #$0f
    sta $d019
    lda #<interrupt_return
    sta $fffa
    sta $fffe
    lda #>interrupt_return
    sta $fffb
    sta $ffff

    lda #$0b
    sta $d011
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #$18
    sta $d018
    sta $d016

    ldx #0
copy_screen:
    .for (var page = 0; page < 4; page++) {
        lda SCREEN_SOURCE + page*$100,x
        sta SCREEN + page*$100,x
    }
    // Start every cell in multicolor mode; apply_phase colors the %11 strip.
    lda #8
    .for (var page = 0; page < 4; page++) {
        sta $d800 + page*$100,x
    }
    inx
    bne copy_screen

    lda #12
    sta $d020
    sta $d021
    jsr apply_phase
    lda #$1b
    sta $d011

wait_lower_border:
    // Raster bit 8 distinguishes line 0 from line 256.
    bit $d011
    bpl wait_lower_border
wait_frame_top:
    bit $d011
    bmi wait_frame_top
frame_ready:
    inc color_ticks
    lda color_ticks
    cmp #FRAMES_PER_COLOR
    bcc wait_lower_border
    lda #0
    sta color_ticks
    inc phase
    lda phase
    cmp #PHASE_COUNT
    bcc phase_ready
    lda #0
    sta phase
phase_ready:
    jsr apply_phase
    jmp wait_lower_border

apply_phase:
    ldx phase
    lda core_luminance,x
    sta $d022
    lda leading_luminance,x
    sta $d023
    lda trailing_luminance,x
    ora #8
    // Only cells containing %11 need a Color RAM write at a phase change.
    .import source "build/demo/tail-stores.asm"
apply_phase_done:
    rts

interrupt_return:
    rti

phase:
    .byte 0
color_ticks:
    .byte 0
trailing_luminance:
    .byte 1,1,0,0,0,1
core_luminance:
    .byte 0,1,1,1,0,0
leading_luminance:
    .byte 0,0,0,1,1,1

* = FONT "Multicolor cube font"
.var font_data = LoadBinary("build/demo/charset.bin")
.if (font_data.getSize() != 2048) {
    .error "Expected one 2048-byte charset"
}
.fill font_data.getSize(), font_data.get(i)

* = SCREEN_SOURCE "Two cube screen"
.var screen_data = LoadBinary("build/demo/screen.bin")
.if (screen_data.getSize() != 1000) {
    .error "Expected one 1000-byte screen"
}
.fill screen_data.getSize(), screen_data.get(i)
.fill 24,0
