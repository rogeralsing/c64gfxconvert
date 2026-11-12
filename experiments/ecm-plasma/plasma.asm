// Independent sine plasma. Static ColorRAM and double-buffered ECM screen codes.
.const SCREEN_0 = $0400
.const SCREEN_1 = $0800
.const FONT_ADDRESS = $2000
.const SINE_ADDRESS = $2300
.const X_STEP_A = 5
.const X_STEP_B = 13
.const Y_STEP_C = 7
.const Y_STEP_D = 17
.label index_a = $02
.label index_b = $03
.label previous_row = $04

.macro plot_rows(screen) {
    .for (var row = 0; row < 25; row++) {
        .byte $cb, 0            // SBX #delta: X=(A&X)-delta, ignoring input carry.
        txa                    // Restore A==X before the next row's SBX.
        sta screen + row*40,y
    }
    rts
}

BasicUpstart2(start)

* = $1000 "ECM sine plasma runtime"
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
    sta $dd0e
    sta $dd0f
    sta $d01a
    sta $d015
    sta front_index
    sta frame_counter
    sta frame_counter+1
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

    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #6
    sta $d020
    lda #4
    sta $d021
    lda #10
    sta $d022
    lda #7
    sta $d023
    lda #1
    sta $d024
    lda #$18
    sta $d018
    lda #$08
    sta $d016

    // Screen $0800 reuses the BASIC stub only after SYS has entered this code.
    ldx #0
!initialize_screens:
    lda #0
    .for (var page = 0; page < 4; page++) {
        sta SCREEN_0 + page*$100,x
        sta SCREEN_1 + page*$100,x
    }
    lda #6
    .for (var page = 0; page < 4; page++) {
        sta $d800 + page*$100,x
    }
    inx
    bne !initialize_screens-

    lda #$00
    sta phase_a
    sta phase_a+1
    sta phase_b
    sta phase_c
    sta phase_d
    sta phase_e
    sta phase_e+1
    lda #$40
    sta phase_b+1
    lda #$80
    sta phase_c+1
    lda #$c0
    sta phase_d+1

    // Prepare phase zero in hidden screen $0800 before the first presentation.
    jsr calculate_plasma
    lda #$5b
    sta $d011
initialization_done:
main:
    jsr wait_frame_boundary
frame_start:
    lda front_index
    eor #1
    sta front_index
    beq !show_screen_0+
    lda #$28
    bne !present+
!show_screen_0:
    lda #$18
!present:
    sta $d018
presentation_start:
frame_presented:
    inc frame_counter
    bne !counter_ready+
    inc frame_counter+1
!counter_ready:
    jsr advance_phases
    jsr calculate_plasma
calculation_done:
frame_ready:
    jmp main

calculate_plasma:
    jsr prepare_columns
    jsr prepare_rows
components_ready:
    jsr patch_rows
plot_start:
    jsr render_columns
plot_done:
    rts

prepare_columns:
    lda phase_a+1
    sta index_a
    lda phase_b+1
    sta index_b
    ldy #0
!column:
    ldx index_a
    lda sine,x
    ldx index_b
    clc
    adc sine,x
    clc
    adc phase_e+1
    sta column_values,y
    lda index_a
    clc
    adc #X_STEP_A
    sta index_a
    lda index_b
    clc
    adc #X_STEP_B
    sta index_b
    iny
    cpy #40
    bne !column-
    rts

prepare_rows:
    lda phase_c+1
    sta index_a
    lda phase_d+1
    sta index_b
    ldy #0
!row:
    ldx index_a
    lda sine,x
    ldx index_b
    clc
    adc sine,x
    sta row_values,y
    lda index_a
    clc
    adc #Y_STEP_C
    sta index_a
    lda index_b
    clc
    adc #Y_STEP_D
    sta index_b
    iny
    cpy #25
    bne !row-
    rts

patch_rows:
    lda #0
    sta previous_row
    .for (var row = 0; row < 25; row++) {
        lda previous_row
        sec
        sbc row_values+row
        sta row_deltas+row
        sta plot_buffer0+row*6+1
        sta plot_buffer1+row*6+1
        lda row_values+row
        sta previous_row
    }
    rts

render_columns:
    lda front_index
    eor #1
    clc
    adc #>plot_buffer0
    sta plot_call+2
    ldy #39
!column:
    ldx column_values,y
    txa
plot_call:
    jsr plot_buffer0
    dey
    bpl !column-
    rts

advance_phases:
    lda phase_a
    clc
    adc #$3d
    sta phase_a
    lda phase_a+1
    adc #$01
    sta phase_a+1
    lda phase_b
    clc
    adc #$b5
    sta phase_b
    lda phase_b+1
    adc #$00
    sta phase_b+1
    lda phase_c
    clc
    adc #$6d
    sta phase_c
    lda phase_c+1
    adc #$ff
    sta phase_c+1
    lda phase_d
    clc
    adc #$67
    sta phase_d
    lda phase_d+1
    adc #$00
    sta phase_d+1
    lda phase_e
    clc
    adc #$71
    sta phase_e
    lda phase_e+1
    adc #$00
    sta phase_e+1
    rts

wait_frame_boundary:
!wait:
    bit $d011
    bmi !wait-
    lda $d012
    cmp #251
    bne !wait-
    rts

interrupt_return:
    rti

front_index:     .byte 0
frame_counter:   .word 0
phase_a:         .word $0000
phase_b:         .word $4000
phase_c:         .word $8000
phase_d:         .word $c000
phase_e:         .word $0000
.assert "Runtime fits below the custom font", * <= FONT_ADDRESS, true

* = FONT_ADDRESS "Full-range triangular ECM font"
font:
    .import binary "build/font.bin"
.assert "ECM font contains 64 glyphs", * - font, 512

* = SINE_ADDRESS "Signed sine lookup"
sine:
    .import binary "build/sine.bin"
.assert "Sine lookup covers every byte phase", * - sine, 256
.assert "Sine lookup is page aligned", <sine, 0

* = $2400 "Per-frame phase components"
column_values:
    .fill 40, 0
* = $2440
row_values:
    .fill 25, 0
* = $2460
row_deltas:
    .fill 25, 0

* = $3000 "Screen-zero SBX row chain"
plot_buffer0:
    :plot_rows(SCREEN_0)
.assert "First row chain contains 25 six-byte cells and RTS", * - plot_buffer0, 151

* = $3100 "Screen-one SBX row chain"
plot_buffer1:
    :plot_rows(SCREEN_1)
.assert "Second row chain contains 25 six-byte cells and RTS", * - plot_buffer1, 151
.assert "Row chains share the same low address", <plot_buffer0, <plot_buffer1
.assert "Row chains occupy adjacent pages", >plot_buffer1, (>plot_buffer0) + 1
