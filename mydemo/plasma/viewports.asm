// Two immutable numeric maps, independent viewports, one freshly composed field.
.const SCREEN = $0400
.const FONT_ADDRESS = $2000
.const FIELD_ADDRESS = $3d00
.const MAP_A_STRIDE = 128
.const MAP_B_STRIDE = 64
.const PALETTE_COUNT = 13
.const PALETTE_HOLD_UPDATES = 125
.label map_a_row_ptrs = $02
.label map_b_column_ptrs = map_a_row_ptrs + 25*2

.macro compose_strip(left) {
    ldy #left
    .for (var row = 0; row < 25; row++) {
        // Alternating row direction carries Y into the next cell. Each cell
        // needs one LDY: A uses its column; transposed B uses its row.
        .var first = left + mod(row, 2)
        .var second = left + 1 - mod(row, 2)
        lda (map_a_row_ptrs + row*2),y
        ldy #row
        adc (map_b_column_ptrs + first*2),y
        sta strength_field + row*40 + first
        lda (map_b_column_ptrs + second*2),y
        ldy #second
        adc (map_a_row_ptrs + row*2),y
        sta strength_field + row*40 + second
    }
}

.macro prepare_a_row(row) {
    lda wave_x + row*8,x
    .if (mod(row, 2) == 0) {
        ldx wave_phase_b
    } else {
        ldx wave_phase_a
    }
    clc
    adc wave_x + row*8,x
    clc
    adc camera_a_x
    bmi !zero+
    cmp #41
    bcc !origin_ready+
    lda #40
    jmp !origin_ready+
!zero:
    lda #0
!origin_ready:
    sta row_x + row
    ora a_row_low
    .if (mod(row, 2) == 1) {
        eor #$80
    }
    sta map_a_row_ptrs + row*2
    lda a_row_high + row,y
    sta map_a_row_ptrs + row*2 + 1
}

.macro prepare_b_column(column) {
    lda wave_y + column*6,x
    .if (mod(column, 2) == 0) {
        ldx wave_phase_b
    } else {
        ldx wave_phase_a
    }
    clc
    adc wave_y + column*6,x
    clc
    adc camera_b_y
    bmi !zero+
    cmp #26
    bcc !origin_ready+
    lda #25
    jmp !origin_ready+
!zero:
    lda #0
!origin_ready:
    sta column_y + column
    ora b_column_low + column,y
    sta map_b_column_ptrs + column*2
    lda b_column_high + column,y
    sta map_b_column_ptrs + column*2 + 1
}

.macro render_row(row) {
    // X supplies both the screen code and foreground lookup index.
    .for (var column = 0; column < 40; column++) {
        ldx strength_field + row*40 + column
        stx SCREEN + row*40 + column
        lda color_map,x
        sta $d800 + row*40 + column
    }
}

BasicUpstart2(start)

* = $1000 "Numeric viewport runtime"
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
    sta frame_counter
    sta frame_counter+1
    sta wave_phase_a
    sta palette_index
    sta palette_pending
    lda #PALETTE_HOLD_UPDATES
    sta palette_ticks
    lda #64
    sta wave_phase_b
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

    lda color_stream
    sta $d020
    sta $d021
    .for (var background = 1; background < 4; background++) {
        lda color_stream + background
        sta $d021 + background
    }
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    jsr refill_color_map
    ldx #0
!initialize_screen:
    lda #0
    .for (var page = 0; page < 4; page++) {
        sta SCREEN + page*$100,x
    }
    lda color_stream + 1
    .for (var page = 0; page < 4; page++) {
        sta $d800 + page*$100,x
    }
    inx
    bne !initialize_screen-

    lda #0
    sta phase_a
    sta phase_a+1
    sta phase_b
    sta phase_c
    sta phase_d
    lda #$40
    sta phase_b+1
    lda #$80
    sta phase_c+1
    lda #$c0
    sta phase_d+1
    lda #$5b
    sta $d011
initialization_done:
    jmp frame_start

cycle_palette:
    // At two PAL fields per numeric update, 125 updates hold each window
    // for about five seconds.
    // The appended stream prefix makes every wrapped window contiguous.
    lda palette_ticks
    bne !countdown+
    lda #PALETTE_HOLD_UPDATES
    sta palette_ticks
    lda palette_index
    clc
    adc #1
    cmp #PALETTE_COUNT
    bcc !palette_ready+
    lda #0
!palette_ready:
    sta palette_index
    jsr refill_color_map
    lda #1
    sta palette_pending
!countdown:
    dec palette_ticks
    rts

refill_color_map:
    ldx palette_index
    .for (var band = 0; band < 4; band++) {
        lda color_stream + band + 1,x
        .for (var value = 0; value < 64; value++) {
            sta color_map + band*64 + value
        }
    }
palette_lookup_ready:
    rts

commit_palette:
palette_commit_start:
    // The beam-following render has finished all foreground stores. Change
    // the globals together in the next top border, before the new row fetch.
    ldx palette_index
    lda color_stream,x
    sta $d021
    .for (var background = 1; background < 4; background++) {
        lda color_stream + background,x
        sta $d021 + background
    }
    lda #0
    sta palette_pending
palette_commit_done:
    rts

update_cameras:
    ldx phase_a+1
    lda motion_x,x
    sta camera_a_x
    ldx phase_b+1
    lda motion_y,x
    sta camera_a_y
    ldx phase_c+1
    lda motion_x,x
    sta camera_b_x
    ldx phase_d+1
    lda motion_y,x
    sta camera_b_y
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
    lda wave_phase_a
    clc
    adc #2
    sta wave_phase_a
    lda wave_phase_b
    clc
    adc #3
    sta wave_phase_b
    rts

wait_render_window:
!wait:
    bit $d011
    bmi !wait-
    lda $d012
    cmp #55
    bne !wait-
    rts

interrupt_return:
    rti

frame_start:
    jsr cycle_palette
palette_cycle_done:
    jsr update_cameras
viewports_ready:
    jsr prepare_map_pointers
compose_start:
    jsr compose_field
compose_done:
    jsr wait_render_window
presentation_start:
    jsr render_field
    lda palette_pending
    beq frame_ready
    jsr commit_palette
frame_ready:
    inc frame_counter
    bne !counter_ready+
    inc frame_counter+1
!counter_ready:
    jsr advance_phases
    jmp frame_start

frame_counter: .word 0
phase_a: .word $0000
phase_b: .word $4000
phase_c: .word $8000
phase_d: .word $c000
camera_a_x: .byte 0
camera_a_y: .byte 0
camera_b_x: .byte 0
camera_b_y: .byte 0
wave_phase_a: .byte 0
wave_phase_b: .byte 64
palette_index: .byte 0
palette_pending: .byte 0
palette_ticks: .byte PALETTE_HOLD_UPDATES
a_row_low: .byte 0
row_x: .fill 25, 0
column_y: .fill 40, 0
.assert "Runtime fits below the motion tables", * <= $1800, true

* = $1800 "Horizontal viewport motion"
motion_x:
    .import binary "build/motion-x.bin"
.assert "Horizontal motion has 256 phases", * - motion_x, 256
* = $1900 "Vertical viewport motion"
motion_y:
    .import binary "build/motion-y.bin"
.assert "Vertical motion has 256 phases", * - motion_y, 256
* = $1a00 "Signed horizontal row wave"
// Repetition wraps phase+spatial offsets while X stays fixed for each layer.
wave_x:
    .import binary "build/wave-x.bin"
    .import binary "build/wave-x.bin"
.assert "Horizontal wave repeats for indexed spatial offsets", * - wave_x, 512
* = $1c00 "Signed vertical column wave"
wave_y:
    .import binary "build/wave-y.bin"
    .import binary "build/wave-y.bin"
.assert "Vertical wave repeats for indexed spatial offsets", * - wave_y, 512
* = $1e00 "Source pointer address tables"
a_row_high: .fill 50, >(map_a + i*MAP_A_STRIDE)
b_column_low: .fill 80, <(map_b + i*MAP_B_STRIDE)
b_column_high: .fill 80, >(map_b + i*MAP_B_STRIDE)
.assert "Pointer address tables fit below the font", * <= FONT_ADDRESS, true

* = FONT_ADDRESS "Accepted monotone ECM font"
font:
    .import binary "build/font.bin"
.assert "ECM font contains 64 glyphs", * - font, 512
* = $2200 "Accepted four-interval foreground lookup"
color_map:
    .import binary "build/color.bin"
.assert "Foreground lookup covers every byte strength", * - color_map, 256
.assert "Foreground lookup is page aligned", <color_map, 0
* = $2300 "Looping colour stream with four-colour lookahead"
color_stream:
    .import binary "build/color-stream.bin"
.assert "Every stream position has a five-colour window", * - color_stream, PALETTE_COUNT+4

* = $2400 "Static numeric map A, 128-byte row pitch"
map_a:
    .import binary "build/map-a.bin"
.assert "Map A contains 50 padded rows", * - map_a, MAP_A_STRIDE*50
.assert "Map A is page aligned", <map_a, 0

* = FIELD_ADDRESS "Fresh common numeric strength field"
strength_field:
    .fill 1024, 0

// Project only after the complete numerical A+B field exists. Raster 55 keeps
// sequential screen and ColorRAM stores behind the old visible row fetches.
* = $4200 "Unrolled accepted ECM projection"
render_field:
render_row_0:
    :render_row(0)
render_row_1:
    :render_row(1)
render_row_2:
    :render_row(2)
render_row_3:
    :render_row(3)
render_row_4:
    :render_row(4)
render_row_5:
    :render_row(5)
render_row_6:
    :render_row(6)
render_row_7:
    :render_row(7)
render_row_8:
    :render_row(8)
render_row_9:
    :render_row(9)
render_row_10:
    :render_row(10)
render_row_11:
    :render_row(11)
render_row_12:
    :render_row(12)
render_row_13:
    :render_row(13)
render_row_14:
    :render_row(14)
render_row_15:
    :render_row(15)
render_row_16:
    :render_row(16)
render_row_17:
    :render_row(17)
render_row_18:
    :render_row(18)
render_row_19:
    :render_row(19)
render_row_20:
    :render_row(20)
render_row_21:
    :render_row(21)
render_row_22:
    :render_row(22)
render_row_23:
    :render_row(23)
render_row_24:
    :render_row(24)
render_end:
    rts
.assert "Projection contains 1000 twelve-byte cells", render_end - render_field, 12000
.assert "Projection fits below composition", * <= $7600, true

* = $7600 "Unrolled fresh viewport composition"
compose_field:
    // Every logical A+B sum is <=255, so every ADC leaves carry clear.
    // Loads, stores and LDY preserve it throughout all twenty strips.
    clc
    .for (var left = 0; left < 40; left += 2) {
        :compose_strip(left)
    }
compose_end:
    rts
.assert "Composition fits below map B", * <= $a000, true

* = $a000 "Static numeric map B, 64-byte column pitch"
map_b:
    .import binary "build/map-b.bin"
.assert "Map B contains 80 padded columns", * - map_b, MAP_B_STRIDE*80
.assert "Map B is page aligned", <map_b, 0

* = $b400 "Prepare independently warped source pointers"
prepare_map_pointers:
    lda camera_a_y
    and #1
    beq !a_low_ready+
    lda #$80
!a_low_ready:
    sta a_row_low
    // Alternate the summand order so X carries the second cursor into
    // the next row or column; each sum needs only one cursor reload.
    ldx wave_phase_a
    ldy camera_a_y
    .for (var row = 0; row < 25; row++) {
        :prepare_a_row(row)
    }
    ldx wave_phase_a
    ldy camera_b_x
    .for (var column = 0; column < 40; column++) {
        :prepare_b_column(column)
    }
    rts
.assert "All native code and maps fit below I/O", * <= $d000, true
