// Add three numeric light fields before mapping their sum through the ECM palette.
.const KERNEL_SIZE = 25
.const KERNEL_NEGATIVE_LIMIT = 256 - (KERNEL_SIZE - 1)
.const PRIMARY_PERIOD = 128
.const PRIMARY_STEP = 3
.const DRIFT_X_PERIOD = 251
.const DRIFT_Y_PERIOD = 239
.const RESET_TIMER_A_PERIOD = 30789
.const RESET_TIMER_B_PERIOD = 320
.const RESET_INTERVAL_CYCLES = RESET_TIMER_A_PERIOD*RESET_TIMER_B_PERIOD
.label field_ptr = $02
.label ball_x = $06
.label rows_left = $07
.label ball_y = $09
.label source_col = $0a
.label source_row = $0b
.label draw_width = $0c
.label dest_x = $0d
.label dest_y = $0e
.label blit_entry_ptr = $0f
.label blit_start_ptr = $11
.label blit_end_ptr = $13
.label saved_end_opcode = $15
.label blit_start_offset = $16
.label blit_end_offset = $17

.macro draw_row(row) {
    .for (var column = 0; column < 40; column++) {
        lda brightness_field + row*40 + column
        sta $0400 + row*40 + column
        tax
        lda color_map,x
        sta $d800 + row*40 + column
    }
}

BasicUpstart2(start)

* = $1000 "Additive ECM metaballs runtime"
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
    sta frame_index
    sta drift_x_index
    sta drift_y_index
    sta timer_started
    sta reset_count
    sta reset_count+1
    lda #6
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
    lda #4
    sta $d022
    lda #10
    sta $d023
    lda #7
    sta $d024
    ldx #0
!clear_display:
    lda #0
    .for (var page = 0; page < 4; page++) {
        sta $0400 + page*$100,x
        sta $d800 + page*$100,x
    }
    inx
    bne !clear_display-
    jsr clear_field
    lda #$5b
    sta $d011

frame_start:
    lda timer_started
    bne timer_poll
    jsr arm_reset_timer
timer_poll:
    // Reading the timer counter avoids the old 6526's destructive ICR race.
!timer_retry:
    lda $dd07
    sta timer_current+1
    lda $dd06
timer_low_sampled:
    sta timer_current
    lda $dd07
    cmp timer_current+1
    bne !timer_retry-
timer_sampled:
    ldx #0
    lda timer_current+1
    cmp timer_previous+1
    bcc !timer_remember+
    bne !timer_wrapped+
    lda timer_current
    cmp timer_previous
    bcc !timer_remember+
    beq !timer_remember+
!timer_wrapped:
    ldx #1
!timer_remember:
    lda timer_current
    sta timer_previous
    lda timer_current+1
    sta timer_previous+1
    cpx #0
    beq fade_start
clear_start:
    jsr clear_field
    inc reset_count
    bne clear_done
    inc reset_count+1
clear_done:
    jmp add_start
fade_start:
    jsr fade_field
add_start:
    .for (var ball = 0; ball < 3; ball++) {
        ldx frame_index
        lda positions + ball*256,x
        ldx drift_x_index
        clc
        adc drift_x + ball*256,x
        sta ball_x
        ldx frame_index
        lda positions + ball*256+128,x
        ldx drift_y_index
        clc
        adc drift_y + ball*256,x
        jsr add_ball
    }
map_start:
    jsr wait_render_window
presentation_start:
    jsr render_field
frame_ready:
    lda frame_index
    clc
    adc #PRIMARY_STEP
    and #(PRIMARY_PERIOD-1)
    sta frame_index
    inc drift_x_index
    lda drift_x_index
    cmp #DRIFT_X_PERIOD
    bcc !drift_x_ready+
    lda #0
    sta drift_x_index
!drift_x_ready:
    inc drift_y_index
    lda drift_y_index
    cmp #DRIFT_Y_PERIOD
    bcc !drift_y_ready+
    lda #0
    sta drift_y_index
!drift_y_ready:
    jmp frame_start

// A and ball_x are signed top-left coordinates. Clip once before adding pixels.
add_ball:
    sta ball_y
    jsr clip_ball
    bcc !visible+
    rts
!visible:
    lda source_col
    asl
    sta blit_start_offset
    lda source_col
    clc
    adc draw_width
    asl
    sta blit_end_offset
    // Generated column indices are relative to the full kernel row. Move the
    // destination base left so the clipped first column still lands on screen.
    sec
    lda field_ptr
    sbc source_col
    sta field_ptr
    lda field_ptr+1
    sbc #0
    sta field_ptr+1
!row:
    ldy source_row
    lda kernel_blit_tables_lo,y
    sta blit_entry_ptr
    lda kernel_blit_tables_hi,y
    sta blit_entry_ptr+1
    ldy blit_start_offset
    lda (blit_entry_ptr),y
    sta blit_start_ptr
    iny
    lda (blit_entry_ptr),y
    sta blit_start_ptr+1
    ldy blit_end_offset
    lda (blit_entry_ptr),y
    sta blit_end_ptr
    iny
    lda (blit_entry_ptr),y
    sta blit_end_ptr+1
    ldy #0
    lda (blit_end_ptr),y
    sta saved_end_opcode
    lda #$60
    sta (blit_end_ptr),y
    jsr call_blit_row
    ldy #0
    lda saved_end_opcode
    sta (blit_end_ptr),y
    clc
    lda field_ptr
    adc #40
    sta field_ptr
    bcc !field_pointer+
    inc field_ptr+1
!field_pointer:
    inc source_row
    dec rows_left
    bne !row-
    rts

// The generated row's RTS returns directly to the caller of this dispatch.
call_blit_row:
    jmp (blit_start_ptr)

// Carry is set for an empty intersection. Visible rectangles get source and
// destination pointers, a clipped width and a clipped row count.
clip_ball:
    lda ball_x
    bmi !negative_x+
    cmp #40
    bcc !positive_x+
    sec
    rts
!positive_x:
    sta dest_x
    lda #0
    sta source_col
    lda #40
    sec
    sbc dest_x
    cmp #KERNEL_SIZE
    bcc !width+
    lda #KERNEL_SIZE
!width:
    sta draw_width
    jmp !clip_y+
!negative_x:
    // Negative coordinates must leave at least one kernel column on screen.
    cmp #KERNEL_NEGATIVE_LIMIT
    bcs !partial_x+
    sec
    rts
!partial_x:
    eor #$ff
    clc
    adc #1
    sta source_col
    lda #0
    sta dest_x
    lda #KERNEL_SIZE
    sec
    sbc source_col
    sta draw_width

!clip_y:
    lda ball_y
    bmi !negative_y+
    cmp #25
    bcc !positive_y+
    sec
    rts
!positive_y:
    sta dest_y
    lda #0
    sta source_row
    lda #25
    sec
    sbc dest_y
    cmp #KERNEL_SIZE
    bcc !height+
    lda #KERNEL_SIZE
!height:
    sta rows_left
    jmp !pointers+
!negative_y:
    cmp #KERNEL_NEGATIVE_LIMIT
    bcs !partial_y+
    sec
    rts
!partial_y:
    eor #$ff
    clc
    adc #1
    sta source_row
    lda #0
    sta dest_y
    lda #KERNEL_SIZE
    sec
    sbc source_row
    sta rows_left

!pointers:
    ldy dest_y
    lda field_row_lo,y
    clc
    adc dest_x
    sta field_ptr
    lda field_row_hi,y
    adc #0
    sta field_ptr+1
    clc
    rts

wait_render_window:
!wait:
    bit $d011
    bmi !wait-
    lda $d012
    cmp #55
    bne !wait-
    rts

// Timer A counts machine clocks; timer B counts A underflows. Neither timer
// restarts when a clear is consumed, so every interval stays 9,852,480 clocks.
arm_reset_timer:
    lda #1
    sta timer_started
    lda #$7f
    sta $dd0d
    lda $dd0d
    lda #<(RESET_TIMER_A_PERIOD-1)
    sta $dd04
    lda #>(RESET_TIMER_A_PERIOD-1)
    sta $dd05
    lda #<(RESET_TIMER_B_PERIOD-1)
    sta $dd06
    sta timer_previous
    lda #>(RESET_TIMER_B_PERIOD-1)
    sta $dd07
    sta timer_previous+1
    lda #$51
    sta $dd0f
    lda #$11
timer_arm_store:
    sta $dd0e
timer_arm:
    rts

interrupt_return:
    rti

frame_index:       .byte 0
drift_x_index:     .byte 0
drift_y_index:     .byte 0
timer_started:     .byte 0
timer_current:     .word 0
timer_previous:    .word RESET_TIMER_B_PERIOD-1
reset_count:       .word 0
.assert "Runtime fits below the fixed font", * < $2000, true

* = $2000 "Phase-continuous 64-glyph ECM dither font"
font:
    .import binary "build/metaballs/font.bin"
.assert "Font contains 64 glyphs", * - font, 512

* = $3000 "Radial kernel and motion tables"
kernel:
    .import binary "build/metaballs/kernel.bin"
.assert "Kernel contains 25x25 brightness values", * - kernel, KERNEL_SIZE*KERNEL_SIZE
.align $100
positions:
    .import binary "build/metaballs/positions.bin"
.assert "Primary motion has six 128-byte planes", * - positions, 6*PRIMARY_PERIOD
.assert "Primary motion is page aligned", <positions, 0
drift_x:
    .import binary "build/metaballs/drift-x.bin"
.assert "X drift has three padded 256-byte planes", * - drift_x, 3*256
.assert "X drift is page aligned", <drift_x, 0
drift_y:
    .import binary "build/metaballs/drift-y.bin"
.assert "Y drift has three padded 256-byte planes", * - drift_y, 3*256
.assert "Y drift is page aligned", <drift_y, 0
.align $100
screen_map:
    .import binary "build/metaballs/map-screen.bin"
.assert "Screen lookup covers every byte brightness", * - screen_map, 256
color_map:
    .import binary "build/metaballs/map-color.bin"
.assert "Color lookup covers every byte brightness", * - color_map, 256
.assert "Foreground lookup is page aligned", <color_map, 0
field_row_lo:
    .fill 25, <(brightness_field+i*40)
field_row_hi:
    .fill 25, >(brightness_field+i*40)
.align $100
fade_map:
    .import binary "build/metaballs/fade.bin"
.assert "Fade lookup covers every byte brightness", * - fade_map, 256
.assert "Fade lookup is page aligned", <fade_map, 0
.assert "Static data fits below offscreen field", * <= $4000, true

* = $4000 "Numeric offscreen brightness field"
brightness_field:
    .fill 1024, 0

// Each 18-cycle cell writes its screen code and foreground together. Starting
// at raster 55 trails every old row fetch and finishes before the next row zero.
* = $5000 "Direct unrolled ECM presentation"
render_field:
render_row_0:
    :draw_row(0)
render_row_1:
    :draw_row(1)
render_row_2:
    :draw_row(2)
render_row_3:
    :draw_row(3)
render_row_4:
    :draw_row(4)
render_row_5:
    :draw_row(5)
render_row_6:
    :draw_row(6)
render_row_7:
    :draw_row(7)
render_row_8:
    :draw_row(8)
render_row_9:
    :draw_row(9)
render_row_10:
    :draw_row(10)
render_row_11:
    :draw_row(11)
render_row_12:
    :draw_row(12)
render_row_13:
    :draw_row(13)
render_row_14:
    :draw_row(14)
render_row_15:
    :draw_row(15)
render_row_16:
    :draw_row(16)
render_row_17:
    :draw_row(17)
render_row_18:
    :draw_row(18)
render_row_19:
    :draw_row(19)
render_row_20:
    :draw_row(20)
render_row_21:
    :draw_row(21)
render_row_22:
    :draw_row(22)
render_row_23:
    :draw_row(23)
render_row_24:
    :draw_row(24)
render_end:
    rts
.assert "Renderer contains 1000 thirteen-byte cells", render_end - render_field, 13000
.assert "Renderer fits below the fade routine", * <= $8300, true

* = $8300 "Numeric field fade"
fade_field:
    ldx #0
!fade_blocks:
    .for (var block = 0; block < 15; block++) {
        ldy brightness_field + block*64,x
        lda fade_map,y
        sta brightness_field + block*64,x
    }
    inx
    cpx #64
    beq !fade_tail+
    jmp !fade_blocks-
!fade_tail:
    // The last block has only 40 logical cells. Leave the 24 padding bytes alone.
    .for (var cell = 960; cell < 1000; cell++) {
        ldy brightness_field + cell
        lda fade_map,y
        sta brightness_field + cell
    }
    rts
.assert "Fade routine fits below the startup clear", * <= $9000, true

* = $9000 "Unrolled numeric field clear"
clear_field:
    lda #0
    .for (var cell = 0; cell < 1000; cell++) {
        sta brightness_field + cell
    }
    rts

* = $a000 "Compiled constant-weight kernel rows"
#import "build/metaballs/kernel-blitters.asm"
.assert "Saturation lookup is page aligned", <saturation, 0
.assert "Saturation lookup covers every byte plus the peak", kernel_blit_tables_lo - saturation, 256 + KERNEL_MAX_WEIGHT
.assert "Compiled kernel blitters fit below I/O", kernel_blitters_end <= $d000, true
