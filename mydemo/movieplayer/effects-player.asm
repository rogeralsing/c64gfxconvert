// ECM version of the direct row-span effects player. Font and source poses
// are frozen assets; only screen bytes and Color RAM values are plotted.
BasicUpstart2(start)
.label source_ptr=$02
.label cache_write=$04
.label top_screen=$06
.label top_color=$08
.label bottom_screen=$0a
.label bottom_color=$0c
.label copy_source=$0e
.label copy_destination=$10
.label row_end=$12
.label color_queue_write=$14
.label stream_index=$16
.label stream_end=$17
.label column=$18
.label clip_min=$19
.label clip_max=$1a
.label run_count=$1b
.label run_end=$1c
.label run_next_column=$1d
.label span_first=$1e
.label span_end=$1f
.macro read_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !done+
    inc source_ptr+1
!done:
}
*=$0820 "High movie boot staging in temporary screen/color work RAM"
high_staging_first: .fill highFirstData.getSize(), highFirstData.get(i)
.assert "First staging below code", * <= $1000, true
*=$1000 "ECM effects player"
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
    sta $d011
    jsr copy_high_payload
    ldx #0
    lda #0
!clear:
    .for(var page=0;page<12;page++) { sta $0400+page*$100,x }
    .for(var page=0;page<4;page++) { sta $d800+page*$100,x }
    inx
    bne !clear-
    lda #12
    sta $d022
    lda #15
    sta $d023
    lda #1
    sta $d024
    lda #$04
    sta front_screen_hi
    lda #$08
    sta back_screen_hi
    lda #$1c
    sta $d018
    lda #8
    sta $d016
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #<interrupt_return
    sta $fffa
    lda #>interrupt_return
    sta $fffb
    lda #<field_irq
    sta $fffe
    lda #>field_irq
    sta $ffff
    lda #$ff
    sta $dc00
    sta $dc02
    lda #0
    sta $dc03
    sta $d012
    jsr reset_mode_clock
    lda #1
    sta $d019
    sta $d01a
    lda #$db
    sta $d011
    cli
    jmp presented
presented:
    nop
prepare_start:
    jsr select_next
    jsr poll_zoom_keyboard
    jsr latch_flash_crop
clear_start:
    jsr clear_back
clear_end:
    nop
cache_start:
    jsr build_cache
cache_end:
    nop
render_start:
    nop
color_queue_start:
    jsr render_rows
color_queue_end:
    nop
render_end:
    nop
!wait:
    jsr wait_field
    lda next_step
    cmp step_index
    beq !cadence+
    lda mode_due
    beq !wait-
!cadence:
commit_start:
    sei
    // Raster256 starts below the old visible matrix. Color cells are copied
    // in row order, keeping the write cursor ahead of the next field's beam.
    lda back_screen_hi
    sta front_screen_hi
    cmp #4
    beq !screen0+
    lda #$2c
    bne !screen+
!screen0:
    lda #$1c
!screen:
    sta $d018
    lda next_mode
    cmp #3
    beq !shift+
    cmp #5
    beq !shift+
    cmp #6
    beq !shift+
    cmp #8
    beq !shift+
    lda #$db
    bne !geometry+
!shift:
    lda #$df
!geometry:
    sta $d011
commit_color_start:
    lda #0
    sta color_fallback
    lda color_changed_count+1
    bne !full_copy+
    lda color_changed_count
    bne !sparse+
    jmp !done+
!sparse:
    jsr commit_color_queues
    jmp !done+
!full_copy:
    inc color_fallback
    // Dense changes keep the previously verified monotonic row-order copy.
    // Sparse changes use constant-color buckets entirely within the border.
    .for(var page=0;page<4;page++) {
        ldx #0
!page:
        .for(var byte=0;byte<4;byte++) {
            lda $0c00+page*$100+byte,x
            sta $d800+page*$100+byte,x
        }
        inx
        inx
        inx
        inx
        bne !page-
    }
!done:
commit_color_end:
    nop
    lda back_screen_hi
    eor #$0c
    sta back_screen_hi
    lda next_step
    cmp step_index
    beq !same+
    sta step_index
    jsr reset_mode_clock
    lda field_counter
    sta mode_started_field
    lda field_counter+1
    sta mode_started_field+1
!same:
    lda next_mode
    sta mode
    lda next_object
    sta object_id
    lda next_film_frame
    sta film_frame
    lda next_serial
    sta film_serial
    lda next_serial+1
    sta film_serial+1
    lda next_phase
    sta phase
    lda latched_zoom_x
    sta active_zoom_x
    lda latched_zoom_y
    sta active_zoom_y
commit_end:
    nop
    cli
    jmp presented

select_next:
    ldx step_index
    inx
    cpx #40
    bcc !candidate+
    ldx #0
!candidate:
    stx candidate_step
    lda step_object,x
    tay
    lda object_budget_base,y
    clc
    adc step_mode,x
    tay
    lda preparation_budget,y
    sta transition_margin
    ldx object_id
    lda object_budget_base,x
    clc
    adc mode
    tax
    lda preparation_budget,x
    clc
    adc transition_margin
    sec
    sbc #1
    sta transition_margin
    lda step_index
    sta next_step
    lda mode_fields_left+1
    bne !chosen+
    lda mode_fields_left
    cmp transition_margin
    bcc !advance+
    bne !chosen+
!advance:
    lda candidate_step
    sta next_step
!chosen:
    ldx next_step
    lda step_mode,x
    sta next_mode
    lda step_object,x
    sta next_object
    cmp object_id
    beq !continue+
    lda #1
    sta next_film_frame
    sta next_serial
    lda #0
    sta next_serial+1
    jmp !phase+
!continue:
    lda film_frame
    clc
    adc #1
    cmp #49
    bcc !pose+
    lda #1
!pose:
    sta next_film_frame
    lda film_serial
    clc
    adc #1
    sta next_serial
    lda film_serial+1
    adc #0
    sta next_serial+1
!phase:
    lda next_film_frame
    cmp #48
    bne !ready+
    lda #0
!ready:
    sta next_phase
    rts
reset_mode_clock:
    lda step_index
    and #1
    bne !flash+
    lda #<501
    ldx #>501
    bne !set+
!flash:
    lda #25
    ldx #0
!set:
    sta mode_fields_left
    stx mode_fields_left+1
    lda #0
    sta mode_due
    rts

latch_flash_crop:
    lda next_mode
    cmp #6
    bne !normal+
    lda next_step
    cmp step_index
    beq !stable+
    lsr
    tax
    lda zoom_x
    clc
    adc flash_dx,x
    bmi !left+
    cmp #21
    bcc !x+
    lda #20
    bne !x+
!left:
    lda #0
!x:
    sta flash_crop_x
    lda zoom_y
    clc
    adc flash_dy,x
    bmi !top+
    cmp #14
    bcc !y+
    lda #13
    bne !y+
!top:
    lda #0
!y:
    sta flash_crop_y
!stable:
    lda flash_crop_x
    sta latched_zoom_x
    lda flash_crop_y
    sta latched_zoom_y
    rts
!normal:
    lda zoom_x
    sta latched_zoom_x
    lda zoom_y
    sta latched_zoom_y
    rts
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
    bne !keys+
    sta keyboard_previous
    rts
!keys:
    cmp keyboard_previous
    beq !done+
    sta keyboard_previous
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

copy_high_payload:
copy_high_start:
    lda #<high_staging_first
    sta copy_source
    lda #>high_staging_first
    sta copy_source+1
    lda #$00
    sta copy_destination
    lda #$e0
    sta copy_destination+1
    lda #<highFirstData.getSize()
    sta copy_left
    lda #>highFirstData.getSize()
    sta copy_left+1
    jsr copy_chunk
    lda #<high_staging_second
    sta copy_source
    lda #>high_staging_second
    sta copy_source+1
    lda #<highRestData.getSize()
    sta copy_left
    lda #>highRestData.getSize()
    sta copy_left+1
    jsr copy_chunk
copy_high_end:
    nop
    rts
copy_chunk:
    lda copy_left
    ora copy_left+1
    beq !done+
    ldy #0
!byte:
    lda (copy_source),y
    sta (copy_destination),y
    inc copy_source
    bne !source+
    inc copy_source+1
!source:
    inc copy_destination
    bne !destination+
    inc copy_destination+1
!destination:
    lda copy_left
    bne !count+
    dec copy_left+1
!count:
    dec copy_left
    lda copy_left
    ora copy_left+1
    bne !byte-
!done:
    rts

.import source "effects-row-cache.asm"

age_to_frame:
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

render_rows:
    lda #25
    sta source_rows
    lda next_mode
    cmp #3
    beq !twelve+
    cmp #5
    beq !twelve+
    cmp #6
    beq !twelve+
    cmp #8
    bne !begin+
!twelve:
    lda #12
    sta source_rows
!begin:
    lda #0
    sta physical_row
!row:
    lda physical_row
    tax
    lda next_mode
    cmp #6
    bne !top+
    txa
    asl
    tax
!top:
    lda row_offset_low,x
    sta top_screen
    sta top_color
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta top_screen+1
    lda row_offset_high,x
    clc
    adc #$0c
    sta top_color+1
    lda next_mode
    cmp #6
    beq !zoom_bottom+
    ldx physical_row
    lda bottom_offset_low,x
    sta bottom_screen
    sta bottom_color
    lda bottom_offset_high,x
    jmp !bottom+
!zoom_bottom:
    inx
    lda row_offset_low,x
    sta bottom_screen
    sta bottom_color
    lda row_offset_high,x
!bottom:
    pha
    clc
    adc back_screen_hi
    sta bottom_screen+1
    pla
    clc
    adc #$0c
    sta bottom_color+1
    lda #0
    sta selected_cache_slot
    lda next_mode
    cmp #1
    bne !draw+
    ldx physical_row
    lda wave_pointer_low,x
    sta wave_load+1
    lda wave_pointer_high,x
    sta wave_load+2
    ldx next_phase
wave_load:
    lda wave_ages,x
    sta selected_cache_slot
!draw:
    jsr draw_row_span
    lda next_mode
    cmp #2
    beq !second+
    cmp #7
    beq !second+
    cmp #8
    bne !next_row+
!second:
    lda #1
    sta selected_cache_slot
    jsr draw_row_span
!next_row:
    inc physical_row
    lda physical_row
    cmp source_rows
    beq !done+
    jmp !row-
!done:
    rts

draw_row_span:
    ldx selected_cache_slot
    lda cache_pointer_low,x
    sta cache_write
    lda cache_pointer_high,x
    sta cache_write+1
    lda physical_row
    ldx next_mode
    cpx #6
    bne !source_y+
    clc
    adc latched_zoom_y
!source_y:
    asl
    tay
    lda (cache_write),y
    sta source_ptr
    iny
    lda (cache_write),y
    sta source_ptr+1
    jsr select_row_plotters
    ldy #0
    lda (source_ptr),y
    sta column
    iny
    lda (source_ptr),y
    clc
    adc #2
    sta stream_end
    lda #2
    sta stream_index
row_token_loop:
    ldy stream_index
    cpy stream_end
    bcs !done+
    lda column
    cmp clip_max
    bcs !done+
    lda (source_ptr),y
    iny
    sty stream_index
    cmp #220
    bcc !dictionary+
    cmp #252
    bcc decode_tone_run
    and #3
    tax
    lda palette_values,x
    sta cell_color
    lda (source_ptr),y
    iny
    sty stream_index
    sta cell_screen
    jmp !scalar+
!dictionary:
    tax
    lda dictionary_color,x
    sta cell_color
    lda dictionary_screen,x
    sta cell_screen
!scalar:
    lda column
    cmp clip_min
    bcc !skip_scalar+
    lda cell_screen
row_cell_call:
    jsr fast_plot_plain
!skip_scalar:
    inc column
    jmp row_token_loop
!done:
    rts

decode_tone_run:
    // Decode a repeated glyph0 once. Its foreground is invisible, so bulk
    // stores never touch the retained foreground shadow or its queues.
    sec
    sbc #220
    pha
    and #7
    clc
    adc #1
    sta run_count
    pla
    and #$18
    asl
    asl
    asl
    sta cell_screen
    lda column
    clc
    adc run_count
    sta run_next_column
    cmp clip_min
    bcc !skip+
    cmp clip_max
    bcc !end+
    lda clip_max
!end:
    sta run_end
    lda column
    cmp clip_min
    bcs !first+
    lda clip_min
!first:
    sta column
    lda run_end
    sec
    sbc column
    sta run_count
    beq !skip+
row_run_call:
    jsr fill_plain_run
!skip:
    lda run_next_column
    sta column
    jmp row_token_loop

select_row_plotters:
    lda #0
    sta clip_min
    lda #40
    sta clip_max
    ldx next_mode
    cpx #3
    bcc !dispatch+
    beq !dispatch+
    cpx #7
    beq !dispatch+
    lda #20
    sta clip_max
    cpx #6
    bne !dispatch+
    lda latched_zoom_x
    sta clip_min
    clc
    adc #20
    sta clip_max
!dispatch:
    cpx #8
    bne !index+
    txa
    clc
    adc selected_cache_slot
    tax
!index:
    lda row_cell_low,x
    sta row_cell_call+1
    lda row_cell_high,x
    sta row_cell_call+2
    lda row_run_low,x
    sta row_run_call+1
    lda row_run_high,x
    sta row_run_call+2
    lda selected_cache_slot
    asl
    asl
    eor physical_row
    and #4
    sta checker_column_bit
    rts

fast_plot_plain:
    ldy column
    sta (top_screen),y
    and #63
    beq !done+
    lda cell_color
    cmp (top_color),y
    beq !done+
    sta (top_color),y
    jmp queue_top_foreground
!done:
    rts
fast_plot_checker:
    lda column
    and #4
    cmp checker_column_bit
    bne !done+
    lda cell_screen
    jmp fast_plot_plain
!done:
    rts
fast_plot_v:
    jsr write_original
    jsr map_v_cell
    ldy column
    jmp write_bottom_mapped
fast_plot_h:
    jsr write_original
    jsr map_h_cell
    ldy column
    lda mirror_column,y
    tay
    jmp write_top_mapped
fast_plot_hv:
    jsr write_original
    jsr map_v_cell
    ldy column
    jsr write_bottom_mapped
    jsr map_h_cell
    ldy column
    lda mirror_column,y
    tay
    jsr write_top_mapped
    jsr map_hv_cell
    ldy column
    lda mirror_column,y
    tay
    jmp write_bottom_mapped
fast_plot_mixed_star:
    jsr write_original
    jsr map_hv_cell
    ldy column
    lda mirror_column,y
    tay
    jmp write_bottom_mapped
fast_plot_mixed_cube:
    jsr map_v_cell
    ldy column
    jsr write_bottom_mapped
    jsr map_h_cell
    ldy column
    lda mirror_column,y
    tay
    jmp write_top_mapped

fill_plain_run:
    ldy column
    ldx run_count
    lda cell_screen
!fill:
    sta (top_screen),y
    iny
    dex
    bne !fill-
    rts
fill_bottom_run:
    ldy column
    ldx run_count
    lda cell_screen
!fill:
    sta (bottom_screen),y
    iny
    dex
    bne !fill-
    rts
fill_v_run:
    ldy column
    ldx run_count
    lda cell_screen
!fill:
    sta (top_screen),y
    sta (bottom_screen),y
    iny
    dex
    bne !fill-
    rts
fill_mirror_top_run:
    lda #40
    sec
    sbc run_end
    tay
    ldx run_count
    lda cell_screen
!fill:
    sta (top_screen),y
    iny
    dex
    bne !fill-
    rts
fill_mirror_bottom_run:
    lda #40
    sec
    sbc run_end
    tay
    ldx run_count
    lda cell_screen
!fill:
    sta (bottom_screen),y
    iny
    dex
    bne !fill-
    rts
fill_mirror_v_run:
    lda #40
    sec
    sbc run_end
    tay
    ldx run_count
    lda cell_screen
!fill:
    sta (top_screen),y
    sta (bottom_screen),y
    iny
    dex
    bne !fill-
    rts
fill_h_run:
    jsr fill_plain_run
    jmp fill_mirror_top_run
fill_hv_run:
    jsr fill_v_run
    jmp fill_mirror_v_run
fill_mixed_star_run:
    jsr fill_plain_run
    jmp fill_mirror_bottom_run
fill_mixed_cube_run:
    jsr fill_bottom_run
    jmp fill_mirror_top_run
fill_zoom_run:
    lda column
    sec
    sbc latched_zoom_x
    asl
    tay
    lda run_count
    asl
    tax
    lda cell_screen
!fill:
    sta (top_screen),y
    sta (bottom_screen),y
    iny
    dex
    bne !fill-
    rts
fill_checker_run:
!chunk:
    lda column
    ora #3
    clc
    adc #1
    cmp run_end
    bcc !end+
    lda run_end
!end:
    sta checker_chunk_end
    lda column
    and #4
    cmp checker_column_bit
    bne !next+
    ldy column
    lda cell_screen
!fill:
    sta (top_screen),y
    iny
    cpy checker_chunk_end
    bne !fill-
!next:
    lda checker_chunk_end
    sta column
    cmp run_end
    bcc !chunk-
    rts

write_original:
    ldy column
    lda cell_screen
    sta (top_screen),y
    and #63
    beq !done+
    lda cell_color
    cmp (top_color),y
    beq !done+
    sta (top_color),y
    jmp queue_top_foreground
!done:
    rts
write_top_mapped:
    lda mapped_screen
    sta (top_screen),y
    and #63
    beq !done+
    lda mapped_color
    cmp (top_color),y
    beq !done+
    sta (top_color),y
    jmp queue_top_foreground
!done:
    rts
write_bottom_mapped:
    lda mapped_screen
    sta (bottom_screen),y
    and #63
    beq !done+
    lda mapped_color
    cmp (bottom_color),y
    beq !done+
    sta (bottom_color),y
    jmp queue_bottom_foreground
!done:
    rts

// The effects write disjoint destinations, so this is each cell's final
// foreground after all spatial/history/zoom transforms. Glyph0 never reads
// Color RAM. Its shadow value may remain until a visible glyph needs it.
queue_top_foreground:
    tax
    lda foreground_queue_bucket,x
    sta foreground_bucket
    tya
    clc
    adc top_color
    sta foreground_position
    lda top_color+1
    adc #$f4
    jmp queue_foreground_position
queue_bottom_foreground:
    tax
    lda foreground_queue_bucket,x
    sta foreground_bucket
    tya
    clc
    adc bottom_color
    sta foreground_position
    lda bottom_color+1
    adc #$f4
queue_foreground_position:
    // The ADC carry above handles cells whose row base crosses a 256-byte
    // screen block. Color is in bits3..2; the physical block is in bits1..0.
    ora foreground_bucket
    tax
    clc
    adc #>color_queue_base
    sta color_queue_write+1
    ldy color_queue_counts,x
    lda foreground_position
    sta (color_queue_write),y
    inc color_queue_counts,x
    inc color_changed_count
    bne queue_foreground_done
    inc color_changed_count+1
queue_foreground_done:
    rts

commit_color_queues:
    lda #0
    sta foreground_commit_bucket
!bucket:
    ldx foreground_commit_bucket
    lda color_queue_counts,x
    beq !next+
    sta color_queue_limit+1
    txa
    clc
    adc #>color_queue_base
    sta color_queue_load+2
    txa
    and #3
    clc
    adc #$d8
    sta color_queue_store+2
    txa
    lsr
    lsr
    tax
    lda palette_values,x
    ldy #0
!position:
color_queue_load:
    ldx color_queue_base,y
color_queue_store:
    sta $d800,x
    iny
color_queue_limit:
    cpy #0
    bne !position-
!next:
    // Page outermost keeps the earliest visible cells first.
    lda foreground_commit_bucket
    clc
    adc #4
    cmp #16
    bcc !again+
    and #3
    clc
    adc #1
    cmp #4
    bcs !done+
!again:
    sta foreground_commit_bucket
    jmp !bucket-
!done:
    rts

plot_zoom:
    lda column
    sec
    sbc latched_zoom_x
    asl
    sta zoom_column
    lda cell_screen
    and #63
    bne !shaped+
    ldy zoom_column
    lda cell_screen
    sta (top_screen),y
    sta (bottom_screen),y
    iny
    sta (top_screen),y
    sta (bottom_screen),y
    rts
!shaped:
    asl
    asl
    sta zoom_index
    lda #0
    sta zoom_quadrant
!quarter:
    lda zoom_index
    clc
    adc zoom_quadrant
    tax
    lda zoom_map,x
    sta mapped_screen
    lda zoom_swap,x
    jsr apply_colors
    lda zoom_quadrant
    and #1
    clc
    adc zoom_column
    tay
    lda zoom_quadrant
    cmp #2
    bcs !bottom+
    jsr write_top_mapped
    jmp !next+
!bottom:
    jsr write_bottom_mapped
!next:
    inc zoom_quadrant
    lda zoom_quadrant
    cmp #4
    bne !quarter-
!done:
    rts

map_h_cell:
    lda cell_screen
    and #63
    tax
    lda h_map,x
    sta mapped_screen
    lda h_swap,x
    jmp apply_colors
map_v_cell:
    lda cell_screen
    and #63
    tax
    lda v_map,x
    sta mapped_screen
    lda v_swap,x
    jmp apply_colors
map_hv_cell:
    lda cell_screen
    and #63
    tax
    lda hv_map,x
    sta mapped_screen
    lda hv_swap,x
apply_colors:
    bne !swap+
    lda cell_color
    sta mapped_color
    lda cell_screen
    and #$c0
    ora mapped_screen
    sta mapped_screen
    rts
!swap:
    lda cell_screen
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    tax
    lda palette_values,x
    sta mapped_color
    ldx cell_color
    lda foreground_background_bits,x
    ora mapped_screen
    sta mapped_screen
    rts

clear_back:
    lda back_screen_hi
    sta clear_page0+2
    clc
    adc #1
    sta clear_page1+2
    adc #1
    sta clear_page2+2
    adc #1
    sta clear_page3+2
    ldx #0
    lda #0
!clear:
clear_page0:
    sta $0400,x
clear_page1:
    sta $0500,x
clear_page2:
    sta $0600,x
clear_page3:
    sta $0700,x
    inx
    bne !clear-
    ldx #15
!queues:
    sta color_queue_counts,x
    dex
    bpl !queues-
    sta color_changed_count
    sta color_changed_count+1
    lda #<color_queue_base
    sta color_queue_write
    rts
wait_field:
    lda field_counter
!wait:
    cmp field_counter
    beq !wait-
    rts
field_irq:
    pha
    lda #1
    sta $d019
    inc field_counter
    bne !counter+
    inc field_counter+1
!counter:
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
    rti
interrupt_return:
    rti

mode: .byte 0
next_mode: .byte 0
object_id: .byte 0
next_object: .byte 0
lookup_object: .byte 0
step_index: .byte 0
next_step: .byte 0
candidate_step: .byte 0
transition_margin: .byte 0
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
front_screen_hi: .byte $04
back_screen_hi: .byte $08
zoom_x: .byte 10
zoom_y: .byte 6
latched_zoom_x: .byte 10
latched_zoom_y: .byte 6
flash_crop_x: .byte 10
flash_crop_y: .byte 6
active_zoom_x: .byte 10
active_zoom_y: .byte 6
keyboard_keys: .byte 0
keyboard_previous: .byte 0
cache_slot: .byte 0
selected_cache_slot: .byte 0
cache_table_count: .byte 0
cache_rows_left: .byte 0
physical_row: .byte 0
source_rows: .byte 25
source_age: .byte 0
run_left: .byte 0
cell_screen: .byte 0
cell_color: .byte 0
mapped_screen: .byte 0
mapped_color: .byte 0
transform_kind: .byte 0
zoom_column: .byte 0
zoom_index: .byte 0
zoom_quadrant: .byte 0
checker_column_bit: .byte 0
checker_chunk_end: .byte 0
copy_left: .word 0
foreground_bucket: .byte 0
foreground_position: .byte 0
foreground_commit_bucket: .byte 0
color_changed_count: .word 0
color_fallback: .byte 0
color_queue_counts: .fill 16,0
cache_frame_ids: .fill 10, 0
cache_object_ids: .fill 10, 0
row_cache: .fill 500, 0
cache_pointer_low: .fill 10, <(row_cache+i*50)
cache_pointer_high: .fill 10, >(row_cache+i*50)
object_frame_base: .byte 0,49,98
object_budget_base: .byte 0,9,18
// Conservative PAL-field preparation envelopes include foreground work,
// Color RAM presentation and badline contention. They are not target FPS.
// Bounds cover all 48 poses, retained FG2 and a cold wave cache. Each adds
// the 12201-cycle full copy, divides by 18456, rounds up and adds one field.
preparation_budget: .byte 5,6,7,4,5,4,8,6,5, 5,6,6,4,5,5,6,6,5, 7,8,10,6,7,7,10,6,5
frame_pointer_low: .fill 147, framePointerData.get(i*2)
frame_pointer_high: .fill 147, framePointerData.get(i*2+1)
.var cellPlotters=List().add(fast_plot_plain,fast_plot_plain,fast_plot_checker,fast_plot_v,fast_plot_h,fast_plot_hv,plot_zoom,fast_plot_checker,fast_plot_mixed_star,fast_plot_mixed_cube)
.var runPlotters=List().add(fill_plain_run,fill_plain_run,fill_checker_run,fill_v_run,fill_h_run,fill_hv_run,fill_zoom_run,fill_checker_run,fill_mixed_star_run,fill_mixed_cube_run)
row_cell_low: .fill 10,<cellPlotters.get(i)
row_cell_high: .fill 10,>cellPlotters.get(i)
row_run_low: .fill 10,<runPlotters.get(i)
row_run_high: .fill 10,>runPlotters.get(i)
row_offset_low: .fill 25, <(i*40)
row_offset_high: .fill 25, >(i*40)
bottom_offset_low: .fill 25, <((23-i)*40)
bottom_offset_high: .fill 25, >((23-i)*40)
mirror_column: .fill 40, 39-i
palette_values: .byte 0,12,15,1
foreground_background_bits: .fill 16, i==12 ? $40 : i==15 ? $80 : i==1 ? $c0 : 0
foreground_queue_bucket: .fill 16, i==12 ? 4 : i==15 ? 8 : i==1 ? 12 : 0
wave_pointer_low: .fill 25, <(wave_ages+i*2)
wave_pointer_high: .fill 25, >(wave_ages+i*2)
wave_ages: .fill waveData.getSize(), waveData.get(i)
step_mode: .fill 40, stepModeData.get(i)
step_object: .fill 40, stepObjectData.get(i)
flash_dx: .fill 20, i-floor(i/6)*6==1 ? -3 : i-floor(i/6)*6==2 ? 2 : i-floor(i/6)*6==3 ? -1 : i-floor(i/6)*6==4 ? 3 : i-floor(i/6)*6==5 ? -2 : 0
flash_dy: .fill 20, i-floor(i/6)*6==1 ? -2 : i-floor(i/6)*6==3 ? 2 : i-floor(i/6)*6==4 ? -1 : i-floor(i/6)*6==5 ? 1 : 0
dictionary_screen: .fill 220, dictionaryScreenData.get(i)
dictionary_color: .fill 220, dictionaryColorData.get(i)
h_map: .fill 64, hMapData.get(i)
h_swap: .fill 64, hSwapData.get(i)
v_map: .fill 64, vMapData.get(i)
v_swap: .fill 64, vSwapData.get(i)
hv_map: .fill 64, hvMapData.get(i)
hv_swap: .fill 64, hvSwapData.get(i)
zoom_map: .fill 256, zoomMapData.get(i)
zoom_swap: .fill 256, zoomSwapData.get(i)
player_code_end:
high_staging_second: .fill highRestData.getSize(), highRestData.get(i)
high_staging_end:
.assert "Code and high staging below font", high_staging_end <= $3000, true
*=$3000 "Frozen mirror-complete ECM font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "64 ECM glyphs", *-font,512
*=$3200 "Direct row spans below I/O"
animation: .fill lowMovieData.getSize(), lowMovieData.get(i)
animation_end:
.assert "No I/O load", animation_end <= $d000, true
.label animation_high=$e000
.label animation_high_end=$e000+highMovieSize
.assert "High movie below vectors", animation_high_end <= $fffa, true
.label color_queue_base=(animation_high_end+$ff)&$ff00
.label color_queue_pool_end=color_queue_base+$1000
.assert "Color queues above immutable movie", color_queue_base >= animation_high_end, true
.assert "Color queues below interrupt vectors", color_queue_pool_end <= $fffa, true
