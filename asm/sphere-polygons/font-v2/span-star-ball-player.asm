// One player: double-speed star and checkerball, seven10-second effects each.
BasicUpstart2(start)
.label source_ptr=$02
.label destination=$04
.label tl_destination=destination
.label tr_destination=$06
.label cache_write=tr_destination
.label bl_destination=$08
.label br_destination=$0a
.label column=$0c
.label span_left=$0d
.label plot_value=$0e
.label source_age=$0f
.label next_row_ptr=$10
.macro read_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !ready+
    inc source_ptr+1
!ready:
}
*=$1000 "Star and checkerball direct raw-span effects"
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
    sta field_counter
    sta field_counter+1
    sta mode
    sta next_mode
    sta film_frame
    sta film_serial
    sta film_serial+1
    sta phase
    sta mode_due
    sta mode_started_field
    sta mode_started_field+1
    sta object_id
    sta next_object
    sta keyboard_previous
    lda #6
    sta mode
    sta next_mode
    lda #10
    sta zoom_x
    sta latched_zoom_x
    sta active_zoom_x
    lda #6
    sta zoom_y
    sta latched_zoom_y
    sta active_zoom_y
    // This standalone player owns a known keyboard idle configuration.
    lda #0
    sta $dc03
    lda #$ff
    sta $dc00
    sta $dc02
    lda #$0b
    sta $d011
    jsr copy_high_payload
    lda #<interrupt_return
    sta $fffa
    lda #>interrupt_return
    sta $fffb
    lda #<field_irq
    sta $fffe
    lda #>field_irq
    sta $ffff
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    ldx #0
!clear:
    lda #0
    .for(var p=0;p<8;p++) { sta $4800+p*$100,x }
    lda #1
    .for(var p=0;p<4;p++) { sta $d800+p*$100,x }
    inx
    bne !clear-
    lda #$48
    sta front_screen_hi
    lda #$4c
    sta back_screen_hi
    lda #$20
    sta $d018
    lda #8
    sta $d016
    jsr reset_mode_clock
    lda #2
    sta frame_wait_fields
    jsr wait_raster_boundary
    lda #$9f
    sta $d011
    lda #0
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    cli
    jmp presented
presented:
    nop
prepare_start:
    jsr select_next
keyboard_start:
    lda next_mode
    cmp #6
    bne !not_zoom+
    jsr poll_zoom_keyboard
    lda zoom_x
    sta latched_zoom_x
    lda zoom_y
    sta latched_zoom_y
    jmp keyboard_end
!not_zoom:
    lda #0
    sta keyboard_previous
keyboard_end:
    nop
    jsr select_zoom_lut
clear_start:
    jsr clear_back
clear_end:
    nop
cache_start:
    lda next_mode
    cmp #3
    bcs !no_cache+
    jsr build_cache
    jmp cache_end
!no_cache:
    lda #0
    sta cache_table_count
cache_end:
    nop
render_start:
    lda next_mode
    cmp #3
    bcs !direct+
    jsr render_cached_rows
    jmp render_end
!direct:
    cmp #6
    beq !zoom+
    jsr render_direct_rows
    jmp render_end
!zoom:
    jsr render_zoom_rows
render_end:
    nop
!wait:
    jsr wait_field
    lda next_mode
    cmp mode
    beq !normal_wait+
    lda mode_due
    beq !wait-
    jmp commit_start
!normal_wait:
    lda frame_wait_fields
    bne !wait-
commit_start:
    sei
    lda next_mode
    cmp mode
    beq !same_mode+
    sta mode
    jsr reset_mode_clock
    lda field_counter
    sta mode_started_field
    lda field_counter+1
    sta mode_started_field+1
!same_mode:
    lda next_mode
    cmp #3
    beq !y7+
    cmp #5
    beq !y7+
    cmp #6
    beq !y7+
    lda #$9b
    bne !geometry+
!y7:
    lda #$9f
!geometry:
    sta $d011
    lda front_screen_hi
    pha
    lda back_screen_hi
    sta front_screen_hi
    cmp #$48
    beq !screen0+
    lda #$30
    bne !d018+
!screen0:
    lda #$20
!d018:
    sta $d018
    pla
    sta back_screen_hi
    lda next_film_frame
    sta film_frame
    lda next_serial
    sta film_serial
    lda next_serial+1
    sta film_serial+1
    lda next_phase
    sta phase
    lda next_object
    sta object_id
    lda latched_zoom_x
    sta active_zoom_x
    lda latched_zoom_y
    sta active_zoom_y
    lda #2
    sta frame_wait_fields
commit_end:
    nop
    cli
    jmp presented

select_next:
    lda mode
    sta next_mode
    lda object_id
    sta next_object
    lda mode_fields_left+1
    bne !same+
    lda mode_fields_left
    cmp #10
    bcs !same+
    inc next_mode
    lda next_mode
    cmp #7
    bcc !same+
    lda #0
    sta next_mode
!same:
    lda mode
    cmp #5
    bne !continue+
    lda next_mode
    cmp #6
    bne !continue+
    lda object_id
    eor #1
    sta next_object
    lda #1
    sta next_film_frame
    sta next_serial
    sta next_phase
    lda #0
    sta next_serial+1
    rts
!continue:
    lda film_frame
    clc
    adc #1
    cmp #49
    bcc !pose+
    lda #1
!pose:
    sta next_film_frame
    cmp #48
    bne !phase+
    lda #0
!phase:
    sta next_phase
    lda film_serial
    clc
    adc #1
    sta next_serial
    lda film_serial+1
    adc #0
    sta next_serial+1
    rts
reset_mode_clock:
    lda #<501
    sta mode_fields_left
    lda #>501
    sta mode_fields_left+1
    lda #0
    sta mode_due
    rts

// Keep the disk/PRG load below I/O. Only after banking out KERNAL, relocate
// the staged whole-frame tail to high RAM; no source frame crosses the gap.
copy_high_payload:
copy_high_start:
    lda #<high_movie_staging
    sta source_ptr
    lda #>high_movie_staging
    sta source_ptr+1
    lda #0
    sta destination
    lda #$e0
    sta destination+1
    lda #<highMovieData.getSize()
    sta high_copy_left
    lda #>highMovieData.getSize()
    sta high_copy_left+1
    ora high_copy_left
    beq copy_high_end
    ldy #0
!byte:
    lda (source_ptr),y
    sta (destination),y
    inc source_ptr
    bne !source+
    inc source_ptr+1
!source:
    inc destination
    bne !destination+
    inc destination+1
!destination:
    lda high_copy_left
    bne !decrement+
    dec high_copy_left+1
!decrement:
    dec high_copy_left
    lda high_copy_left
    ora high_copy_left+1
    bne !byte-
copy_high_end:
    nop
    rts

// The current hidden image chooses all source and semantic-zoom tables from
// next_object. The displayed object_id is unchanged until lower-border commit.
set_source_pointer:
    ldx next_object
    beq !index+
    clc
    adc #49
!index:
    tax
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    rts
select_zoom_lut:
    ldx next_object
    lda zoom_tl_high,x
    sta zoom_load_tl+2
    lda zoom_tr_high,x
    sta zoom_load_tr+2
    lda zoom_bl_high,x
    sta zoom_load_bl+2
    lda zoom_br_high,x
    sta zoom_load_br+2
    rts

// Direct CIA1 scan: PA1 selects W/A/S; PA2 selects D. Every poll restores
// the owned idle PRA=$ff, DDRA=$ff, DDRB=0; IRQ uses no CIA or shared scratch.
poll_zoom_keyboard:
    lda #$fd
    sta $dc00
    lda $dc01
    eor #$ff
    and #$26
    sta keyboard_keys
    lda #$fb
    sta $dc00
    lda $dc01
    eor #$ff
    and #4
    asl
    ora keyboard_keys
    sta keyboard_keys
    lda #$ff
    sta $dc00
    lda keyboard_keys
    bne !held+
    sta keyboard_previous
    rts
!held:
    cmp keyboard_previous
    beq !repeat+
    sta keyboard_previous
    lda #10
    sta keyboard_repeat_delay
    jmp !move+
!repeat:
    lda field_counter
    sec
    sbc keyboard_repeat_field
    cmp keyboard_repeat_delay
    bcs !repeat_ready+
    rts
!repeat_ready:
    lda #4
    sta keyboard_repeat_delay
!move:
    lda field_counter
    sta keyboard_repeat_field
    lda keyboard_keys
    and #$22
    cmp #2
    bne !down+
    lda zoom_y
    beq !horizontal+
    dec zoom_y
    jmp !horizontal+
!down:
    cmp #$20
    bne !horizontal+
    lda zoom_y
    cmp #13
    bcs !horizontal+
    inc zoom_y
!horizontal:
    lda keyboard_keys
    and #$0c
    cmp #4
    bne !right+
    lda zoom_x
    beq !done+
    dec zoom_x
    rts
!right:
    cmp #8
    bne !done+
    lda zoom_x
    cmp #20
    bcs !done+
    inc zoom_x
!done:
    rts

render_zoom_rows:
zoom_render_start:
    nop
    lda next_film_frame
    jsr set_source_pointer
    lda latched_zoom_y
    sta zoom_rows_to_skip
!skip:
    lda zoom_rows_to_skip
    beq !start+
    ldy #1
    lda (source_ptr),y
    clc
    adc #2
    clc
    adc source_ptr
    sta source_ptr
    bcc !skip_ready+
    inc source_ptr+1
!skip_ready:
    dec zoom_rows_to_skip
    jmp !skip-
!start:
    lda latched_zoom_x
    clc
    adc #20
    sta zoom_crop_end
    lda #0
    sta physical_row
!row:
    lda physical_row
    asl
    tax
    lda row_offset_low,x
    sta tl_destination
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta tl_destination+1
    inx
    lda row_offset_low,x
    sta bl_destination
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta bl_destination+1
    :read_byte()
    sta column
    :read_byte()
    sta span_left
    clc
    adc source_ptr
    sta next_row_ptr
    lda source_ptr+1
    adc #0
    sta next_row_ptr+1
    lda latched_zoom_x
    sec
    sbc column
    bcc !left_ready+
    cmp span_left
    bcc !skip_left+
    jmp !next_row+
!skip_left:
    sta zoom_skip
    clc
    adc source_ptr
    sta source_ptr
    bcc !skip_left_ready+
    inc source_ptr+1
!skip_left_ready:
    lda span_left
    sec
    sbc zoom_skip
    sta span_left
    lda latched_zoom_x
    sta column
!left_ready:
    lda column
    cmp zoom_crop_end
    bcs !next_row+
    lda zoom_crop_end
    sec
    sbc column
    cmp span_left
    bcs !length_ready+
    sta span_left
!length_ready:
    lda span_left
    beq !next_row+
    lda column
    sec
    sbc latched_zoom_x
    asl
    sta column
!glyph:
    :read_byte()
    tax
    ldy column
zoom_load_tl:
    lda zoom_tl_lut,x
zoom_store_tl:
    sta (tl_destination),y
zoom_load_bl:
    lda zoom_bl_lut,x
zoom_store_bl:
    sta (bl_destination),y
    iny
zoom_load_tr:
    lda zoom_tr_lut,x
zoom_store_tr:
    sta (tl_destination),y
zoom_load_br:
    lda zoom_br_lut,x
zoom_store_br:
    sta (bl_destination),y
    inc column
    inc column
    dec span_left
    bne !glyph-
!next_row:
    lda next_row_ptr
    sta source_ptr
    lda next_row_ptr+1
    sta source_ptr+1
    inc physical_row
    lda physical_row
    cmp #12
    beq zoom_render_end
    jmp !row-
zoom_render_end:
    nop
    rts

// Reuse one500-byte pool: normal1table, wave10tables, checker2tables.
// Table slots store interleaved absolute row-record pointers (25x2bytes).
build_cache:
    lda #1
    sta cache_table_count
    lda next_mode
    cmp #1
    bne !checker+
    lda #10
    sta cache_table_count
!checker:
    cmp #2
    bne !start+
    lda #2
    sta cache_table_count
!start:
    lda #0
    sta cache_slot
!table:
    lda cache_slot
    sta source_age
    lda next_mode
    cmp #2
    bne !age+
    lda cache_slot
    beq !age+
    lda #24
    sta source_age
!age:
    jsr age_to_source_frame
    ldx cache_slot
    sta cache_frame_ids,x
    jsr set_source_pointer
    ldx cache_slot
    lda cache_pointer_low,x
    sta cache_write
    lda cache_pointer_high,x
    sta cache_write+1
    lda #25
    sta cache_rows_left
!row:
    ldy #0
    lda source_ptr
    sta (cache_write),y
    iny
    lda source_ptr+1
    sta (cache_write),y
    lda (source_ptr),y
    clc
    adc #2
    clc
    adc source_ptr
    sta source_ptr
    bcc !source_ready+
    inc source_ptr+1
!source_ready:
    lda cache_write
    clc
    adc #2
    sta cache_write
    bcc !cache_ready+
    inc cache_write+1
!cache_ready:
    dec cache_rows_left
    bne !row-
    inc cache_slot
    lda cache_slot
    cmp cache_table_count
    bne !table-
    rts

age_to_source_frame:
    lda next_serial+1
    bne !positive+
    lda next_serial
    cmp source_age
    beq !blank+
    bcc !blank+
!positive:
    lda next_film_frame
    sec
    sbc source_age
    bcs !nonnegative+
    clc
    adc #48
    rts
!nonnegative:
    bne !done+
    lda #48
!done:
    rts
!blank:
    lda #0
    rts

render_cached_rows:
    lda #0
    sta physical_row
!row:
    ldx physical_row
    lda row_offset_low,x
    sta destination
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta destination+1
    lda #0
    sta selected_cache_slot
    sta mask_mode
    lda next_mode
    cmp #1
    bne !not_wave+
    lda wave_pointer_low,x
    sta wave_load+1
    lda wave_pointer_high,x
    sta wave_load+2
    ldx next_phase
wave_load:
    lda wave_ages,x
    sta selected_cache_slot
!not_wave:
    lda next_mode
    cmp #2
    bne !draw_a+
    lda #1
    sta mask_mode
!draw_a:
    jsr setup_clip
    jsr draw_cached_span
    lda next_mode
    cmp #2
    bne !next_row+
    lda #1
    sta selected_cache_slot
    lda #2
    sta mask_mode
    jsr setup_clip
    jsr draw_cached_span
!next_row:
    inc physical_row
    lda physical_row
    cmp #25
    bne !row-
    rts

// Mirror modes read independent source headers directly; the cache pool is idle.
render_direct_rows:
    lda #12
    sta source_rows
    lda #20
    sta column_limit
    lda next_mode
    cmp #3
    bne !horizontal+
    lda #40
    sta column_limit
!horizontal:
    lda next_mode
    cmp #4
    bne !limits_ready+
    lda #25
    sta source_rows
!limits_ready:
    lda next_film_frame
    jsr set_source_pointer
    lda #0
    sta physical_row
!row:
    ldx physical_row
    lda row_offset_low,x
    sta tl_destination
    sta tr_destination
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta tl_destination+1
    sta tr_destination+1
    lda next_mode
    cmp #4
    beq !destinations_ready+
    lda bottom_offset_low,x
    sta bl_destination
    sta br_destination
    lda bottom_offset_high,x
    clc
    adc back_screen_hi
    sta bl_destination+1
    sta br_destination+1
!destinations_ready:
direct_span_start:
    :read_byte()
    sta column
    :read_byte()
    sta span_left
    clc
    adc source_ptr
    sta next_row_ptr
    lda source_ptr+1
    adc #0
    sta next_row_ptr+1
    lda column
    cmp column_limit
    bcs !next_row+
    lda column_limit
    sec
    sbc column
    cmp span_left
    bcs !length_ready+
    sta span_left
!length_ready:
    lda span_left
    beq !next_row+
!glyph:
    :read_byte()
    tax
    ldy column
    txa
store_original:
    sta (tl_destination),y
    lda next_mode
    cmp #4
    beq !horizontal_glyph+
    lda v_lut,x
store_v:
    sta (bl_destination),y
    lda next_mode
    cmp #3
    beq !plotted+
!horizontal_glyph:
    lda h_lut,x
    tax
    lda mirror_column,y
    tay
    txa
store_h:
    sta (tr_destination),y
    lda next_mode
    cmp #5
    bne !plotted+
    lda v_lut,x
store_both:
    sta (br_destination),y
!plotted:
    inc column
    dec span_left
    bne !glyph-
!next_row:
direct_span_end:
    nop
    lda next_row_ptr
    sta source_ptr
    lda next_row_ptr+1
    sta source_ptr+1
    inc physical_row
    lda physical_row
    cmp source_rows
    beq !done+
    jmp !row-
!done:
    rts

draw_cached_span:
    ldx selected_cache_slot
    lda cache_pointer_low,x
    sta cache_write
    lda cache_pointer_high,x
    sta cache_write+1
    lda physical_row
    asl
    tay
    lda (cache_write),y
    sta source_ptr
    iny
    lda (cache_write),y
    sta source_ptr+1
span_start:
    :read_byte()
    sta column
    :read_byte()
    sta span_left
    lda span_left
    beq span_end
!copy:
    :read_byte()
    jsr plot_dispatch
    dec span_left
    bne !copy-
span_end:
    nop
    rts
setup_clip:
    lda mask_mode
    bne !checker+
    lda #<plot_all
    sta plot_dispatch+1
    lda #>plot_all
    sta plot_dispatch+2
    rts
!checker:
    lda #<plot_clipped
    sta plot_dispatch+1
    lda #>plot_clipped
    sta plot_dispatch+2
    lda physical_row
    lsr
    lsr
    and #1
    sta clip_parity
    lda mask_mode
    cmp #1
    beq !parity+
    lda clip_parity
    eor #1
    sta clip_parity
!parity:
    lda clip_parity
    beq !even+
    lda #<clip_odd
    ldx #>clip_odd
    jmp !patch+
!even:
    lda #<clip_even
    ldx #>clip_even
!patch:
    sta clip_load+1
    stx clip_load+2
    rts

plot_dispatch:
    jmp plot_all
plot_all:
    ldy column
packet_store_all:
    sta (destination),y
    inc column
    rts
plot_clipped:
    sta plot_value
    ldy column
clip_load:
    lda clip_even,y
    beq clip_reject
    lda plot_value
packet_store:
    sta (destination),y
clip_reject:
    inc column
    rts

clear_back:
    lda #0
    sta destination
    lda back_screen_hi
    sta destination+1
    ldx #4
    ldy #0
    lda #0
!clear:
    sta (destination),y
    iny
    bne !clear-
    inc destination+1
    dex
    bne !clear-
    rts

wait_field:
    lda field_counter
!wait:
    cmp field_counter
    beq !wait-
    rts
wait_raster_boundary:
!low:
    bit $d011
    bmi !low-
!high:
    bit $d011
    bpl !high-
    rts

field_irq:
    pha
    lda #1
    sta $d019
    inc field_counter
    bne !field+
    inc field_counter+1
!field:
    lda frame_wait_fields
    beq !mode+
    dec frame_wait_fields
!mode:
    lda mode_due
    bne field_complete
    lda mode_fields_left
    bne !decrement+
    dec mode_fields_left+1
!decrement:
    dec mode_fields_left
    lda mode_fields_left
    ora mode_fields_left+1
    bne field_complete
    lda #1
    sta mode_due
field_complete:
    nop
    pla
irq_return:
    rti
interrupt_return:
    rti

mode: .byte 0
next_mode: .byte 0
object_id: .byte 0
next_object: .byte 0
high_copy_left: .word 0
film_frame: .byte 0
next_film_frame: .byte 0
film_serial: .word 0
next_serial: .word 0
phase: .byte 0
next_phase: .byte 0
field_counter: .word 0
mode_started_field: .word 0
mode_fields_left: .word 501
mode_due: .byte 0
frame_wait_fields: .byte 2
front_screen_hi: .byte $48
back_screen_hi: .byte $4c
physical_row: .byte 0
mask_mode: .byte 0
clip_parity: .byte 0
cache_slot: .byte 0
cache_table_count: .byte 0
cache_rows_left: .byte 0
selected_cache_slot: .byte 0
source_rows: .byte 12
column_limit: .byte 20
zoom_x: .byte 10
zoom_y: .byte 6
latched_zoom_x: .byte 10
latched_zoom_y: .byte 6
active_zoom_x: .byte 10
active_zoom_y: .byte 6
zoom_rows_to_skip: .byte 0
zoom_crop_end: .byte 30
zoom_skip: .byte 0
keyboard_keys: .byte 0
keyboard_previous: .byte 0
keyboard_repeat_delay: .byte 10
keyboard_repeat_field: .byte 0
cache_frame_ids: .fill 10, 0
row_cache: .fill 500, 0
cache_pointer_low: .fill 10, <(row_cache+i*50)
cache_pointer_high: .fill 10, >(row_cache+i*50)
frame_pointer_low: .fill 98, absoluteIndexData.get(i)
frame_pointer_high: .fill 98, absoluteIndexData.get(i+98)
row_offset_low: .fill 25, <(i*40)
row_offset_high: .fill 25, >(i*40)
bottom_offset_low: .fill 12, <((23-i)*40)
bottom_offset_high: .fill 12, >((23-i)*40)
mirror_column: .fill 20, 39-i
clip_even: .fill 40, (floor(i/4)&1)==0 ? 1 : 0
clip_odd: .fill 40, (floor(i/4)&1)==1 ? 1 : 0
wave_pointer_low: .fill 25, <(wave_ages+i*48)
wave_pointer_high: .fill 25, >(wave_ages+i*48)
wave_ages: .fill waveData.getSize(), waveData.get(i)
zoom_tl_high: .byte >zoom_tl_lut, >zoom_ball_tl_lut
zoom_tr_high: .byte >zoom_tr_lut, >zoom_ball_tr_lut
zoom_bl_high: .byte >zoom_bl_lut, >zoom_ball_bl_lut
zoom_br_high: .byte >zoom_br_lut, >zoom_ball_br_lut
.align $100
h_lut: .fill 256, hData.get(i)
v_lut: .fill 256, vData.get(i)
zoom_tl_lut: .fill 256, zoomData.get(i*4)
zoom_tr_lut: .fill 256, zoomData.get(i*4+1)
zoom_bl_lut: .fill 256, zoomData.get(i*4+2)
zoom_br_lut: .fill 256, zoomData.get(i*4+3)
zoom_ball_tl_lut: .fill 256, ballZoomData.get(i*4)
zoom_ball_tr_lut: .fill 256, ballZoomData.get(i*4+1)
zoom_ball_bl_lut: .fill 256, ballZoomData.get(i*4+2)
zoom_ball_br_lut: .fill 256, ballZoomData.get(i*4+3)
player_code_end:
.assert "Code and wave LUT below font", player_code_end <= $4000, true
high_movie_staging: .fill highMovieData.getSize(), highMovieData.get(i)
high_movie_staging_end:
.assert "High payload staging below font", high_movie_staging_end <= $4000, true
*=$4000 "Locked unchanged font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Full font", *-font, 2048
*=$5000 "Independent raw X,length,chars rows"
animation: .fill lowMovieData.getSize(), lowMovieData.get(i)
animation_end:
.assert "Spans below I/O", animation_end <= $d000, true
.label animation_high=$e000
.label animation_high_end=$e000+highMovieData.getSize()
.assert "High spans below interrupt vectors", animation_high_end <= $fffa, true
