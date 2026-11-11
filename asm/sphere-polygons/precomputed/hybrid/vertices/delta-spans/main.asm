// Source-certified incremental geometry: compare old/new mathematical spans.
BasicUpstart2(start)
.label coverage=$1000
.label dirty=$1400
.label old_left=$0c00
.label old_right=$0c80
.label new_left=$0d00
.label new_right=$0d80
.label movie_ptr=$02
.label pattern_ptr=$04
.label record_ptr=$06
.label coverage_ptr=$08
.label screen_ptr=$0a
.label clip_lo_ptr=$0c
.label clip_hi_ptr=$0e
.label remap_ptr=$10
.label current_face_index=$12
.label raster_vertex_count=$13
.label old_first=$14
.label old_end=$15
.label new_first=$16
.label new_end=$17
.label work_first=$18
.label work_end=$19
.label span_base=$1a
.label decode_l=$1b
.label decode_r=$1c
.label sample_index=$1d
.label update_mode=$1e
.label source_l=$1f
.label source_r=$20
.label target_l=$21
.label target_r=$22
.label band_l=$23
.label band_r=$24
.label col_l=$25
.label col_r=$26
.label mask_l=$27
.label mask_r=$28
.label full_mask=$29
.label sample_part=$2a
.label row_lo=$2b
.label row_hi=$2c
.label work_mask=$2d
.label cell_lo=$2e
.label cell_hi=$2f
.label bit_mask=$30
.label temp=$31
.label visible_bits=$32
.label offset_lo=$33
.label resolve_bits=$34
.label dirty_index=$35
.label saved_y=$36
.label resolved_glyph=$37
.label old_visible=$38
.label new_visible=$39
.label old_base_hi=$3a
.label new_base_hi=$3b
.var movieData=LoadBinary("build/assets/spans.sa64")
.assert "SA64 faces",movieData.get(5),36
.assert "SA64 frames",movieData.get(6)+256*movieData.get(7),64

*=$2000 "Fixed mathematical font"
font: .import binary "build/assets/font.bin"
*=$2800 "Incremental geometry player"
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
    sta frame_index
    sta frame_counter
    sta frame_counter+1
    sta display_initialized
    lda #$0b
    sta $d011
    lda #15
    sta $d019
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
    ldx #0
!clear:
    lda #0
    .for(var page=0;page<4;page++) {
        sta $0400+page*$100,x
        sta coverage+page*$100,x
    }
    sta dirty,x
    sta $1500,x
    sta $1600,x
    lda #1
    .for(var page=0;page<4;page++){sta $d800+page*$100,x}
    inx
    bne !clear-
    lda #$15
    sta old_base_hi
    lda #$16
    sta new_base_hi
    lda #$18
    sta $d018
    lda #8
    sta $d016

render_start:
decode_start:
    jsr decode_frame
decode_end:
    nop
clear_start:
    lda #0
    sta dirty_count
    sta dirty_count+1
    sta add_masks
    sta add_masks+1
    sta remove_masks
    sta remove_masks+1
    sta screen_writes
    sta screen_writes+1
clear_end:
    nop
    jsr update_faces
    ldx old_base_hi
    lda new_base_hi
    sta old_base_hi
    stx new_base_hi
resolve_start:
    jsr resolve_dirty
resolve_end:
    nop
    lda #1
    sta display_initialized
wait_start:
    jsr wait_boundary
    lda #$1b
    sta $d011
flush_start:
    jsr flush_queue
flush_end:
    nop
render_end:
    jsr wait_boundary
frame_boundary:
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    inc frame_index
    lda frame_index
    cmp #64
    bne !next+
    lda #0
    sta frame_index
!next:
    jmp render_start

read_movie:
    ldy #0
    lda (movie_ptr),y
    inc movie_ptr
    bne !done+
    inc movie_ptr+1
!done:
    rts
read_pattern:
    ldy #0
    lda (pattern_ptr),y
    inc pattern_ptr
    bne !done+
    inc pattern_ptr+1
!done:
    rts

decode_frame:
    lda frame_index
    bne !ready+
    lda #<movie_first_frame
    sta movie_ptr
    lda #>movie_first_frame
    sta movie_ptr+1
!ready:
    lda #$90
    sta record_ptr
    lda new_base_hi
    sta record_ptr+1
    ldx #0
!vis:
    jsr read_movie
    pha
    txa
    tay
    pla
    sta (record_ptr),y
    inx
    cpx #5
    bne !vis-
    lda #0
    sta current_face_index
!face:
    lda new_base_hi
    jsr get_visible
    beq !next+
    lda current_face_index
    asl
    asl
    sta record_ptr
    lda new_base_hi
    sta record_ptr+1
    ldx #0
!record:
    jsr read_movie
    pha
    txa
    tay
    pla
    sta (record_ptr),y
    inx
    cpx #4
    bne !record-
!next:
    inc current_face_index
    lda current_face_index
    cmp #36
    bcc !face-
    rts

get_visible:
    sta record_ptr+1
    lda #$90
    sta record_ptr
    lda current_face_index
    and #7
    tax
    lda bit_masks,x
    sta visible_bits
    lda current_face_index
    lsr
    lsr
    lsr
    tay
    lda (record_ptr),y
    and visible_bits
    rts

update_faces:
    lda #0
    sta current_face_index
!face:
    lda old_base_hi
    jsr get_visible
    sta old_visible
    lda new_base_hi
    jsr get_visible
    sta new_visible
    ora old_visible
    bne !active+
    jmp !next+
!active:
    ldx current_face_index
    lda movie_counts,x
    sta raster_vertex_count
face_edges_start:
edge_start:
    lda old_visible
    bne !old+
    lda #0
    sta old_first
    sta old_end
    beq !new+
!old:
    lda old_base_hi
    ldy #$0c
    jsr decode_spans
    lda work_first
    sta old_first
    lda work_end
    sta old_end
!new:
    lda new_visible
    bne !new_active+
    lda #0
    sta new_first
    sta new_end
    beq !decoded+
!new_active:
    lda new_base_hi
    ldy #$0d
    jsr decode_spans
    lda work_first
    sta new_first
    lda work_end
    sta new_end
!decoded:
face_edges_end:
edge_end:
    nop
face_fill_start:
fill_start:
    jsr compare_spans
face_fill_end:
fill_end:
    nop
!next:
    inc current_face_index
    lda current_face_index
    cmp #36
    bcs !done+
    jmp !face-
!done:
    rts

// A=record base high, Y=scratch page ($0c old/$0d new).
decode_spans:
    sta record_ptr+1
    sty store_left+2
    sty store_right+2
    lda current_face_index
    asl
    asl
    sta record_ptr
    ldy #0
    lda (record_ptr),y
    sta work_first
    iny
    lda (record_ptr),y
    sta span_base
    iny
    lda (record_ptr),y
    clc
    adc #<span_pool
    sta pattern_ptr
    iny
    lda (record_ptr),y
    adc #>span_pool
    sta pattern_ptr+1
    jsr read_pattern
    clc
    adc work_first
    sta work_end
    ldx work_first
    cpx work_end
    beq !done+
    jsr read_pattern
    clc
    adc span_base
    sta decode_l
    jsr read_pattern
    clc
    adc span_base
    sta decode_r
    jmp !store+
!sample:
    jsr read_pattern
    cmp #255
    beq !absolute+
    pha
    and #15
    sec
    sbc #7
    clc
    adc decode_l
    sta decode_l
    pla
    lsr
    lsr
    lsr
    lsr
    sec
    sbc #7
    clc
    adc decode_r
    sta decode_r
    jmp !store+
!absolute:
    jsr read_pattern
    clc
    adc span_base
    sta decode_l
    jsr read_pattern
    clc
    adc span_base
    sta decode_r
!store:
    lda decode_l
store_left:
    sta old_left,x
    lda decode_r
store_right:
    sta old_right,x
    inx
    cpx work_end
    bcc !sample-
!done:
    rts

compare_spans:
    lda old_end
    beq !only_new+
    lda new_end
    beq !only_old+
    lda old_first
    cmp new_first
    bcc !start+
!only_new:
    lda new_first
    jmp !start+
!only_old:
    lda old_first
!start:
    sta sample_index
!sample:
    ldx sample_index
    cpx old_end
    bcs !old_empty+
    cpx old_first
    bcc !old_empty+
    lda old_left,x
    sta source_l
    lda old_right,x
    sta source_r
    jmp !new+
!old_empty:
    lda #0
    sta source_l
    sta source_r
!new:
    cpx new_end
    bcs !new_empty+
    cpx new_first
    bcc !new_empty+
    lda new_left,x
    sta target_l
    lda new_right,x
    sta target_r
    jmp !row+
!new_empty:
    lda #0
    sta target_l
    sta target_r
!row:
    lda sample_row_lo,x
    sta coverage_ptr
    sta row_lo
    lda sample_row_hi,x
    sta row_hi
    clc
    adc #>coverage
    sta coverage_ptr+1
    lda sample_parts,x
    sta sample_part
    lsr
    lsr
    lsr
    tax
    lda full_masks,x
    sta full_mask
    lda #0
    sta update_mode
    jsr difference_bands
    lda source_l
    ldx target_l
    sta target_l
    stx source_l
    lda source_r
    ldx target_r
    sta target_r
    stx source_r
    lda #1
    sta update_mode
    jsr difference_bands
    inc sample_index
    lda sample_index
    cmp old_end
    bcs !check_new+
    jmp !sample-
!check_new:
    cmp new_end
    bcs !done+
    jmp !sample-
!done:
    rts

// Toggle source interval minus target interval: at most two bands.
difference_bands:
    lda source_l
    cmp source_r
    bcc !source_valid+
    rts
!source_valid:
    lda target_l
    cmp target_r
    bcc !target_valid+
    lda source_l
    sta band_l
    lda source_r
    sta band_r
    jmp toggle_interval
!target_valid:
    lda source_l
    cmp target_l
    bcs !right+
    sta band_l
    lda source_r
    cmp target_l
    bcc !left_end+
    lda target_l
!left_end:
    sta band_r
    jsr toggle_interval
!right:
    lda target_r
    cmp source_r
    bcs !done+
    cmp source_l
    bcs !right_start+
    lda source_l
!right_start:
    sta band_l
    lda source_r
    sta band_r
    jmp toggle_interval
!done:
    rts

toggle_interval:
    lda band_l
    cmp band_r
    bcc !nonempty+
    rts
!nonempty:
    lsr
    lsr
    lsr
    sta col_l
    lda band_r
    lsr
    lsr
    lsr
    sta col_r
    lda band_l
    and #7
    ora sample_part
    tax
    lda left_masks,x
    sta mask_l
    lda band_r
    and #7
    ora sample_part
    tax
    lda right_masks,x
    sta mask_r
    ldy col_l
    cpy col_r
    bne !multiple+
    lda mask_l
    and mask_r
    jmp toggle_mask
!multiple:
    lda mask_l
    jsr toggle_mask
    iny
!interior:
    cpy col_r
    bcs !right+
    lda full_mask
    jsr toggle_mask
    iny
    jmp !interior-
!right:
    lda mask_r
    jmp toggle_mask

toggle_mask:
    cmp #0
    bne !nonzero+
    rts
!nonzero:
    ldx update_mode
    beq !remove+
    inc add_masks
    bne !counted+
    inc add_masks+1
    jmp !counted+
!remove:
    inc remove_masks
    bne !counted+
    inc remove_masks+1
!counted:
    eor (coverage_ptr),y
coverage_store:
    sta (coverage_ptr),y
    tya
    clc
    adc row_lo
    sta cell_lo
    lda row_hi
    adc #0
    sta cell_hi
    lda cell_lo
    and #7
    tax
    lda bit_masks,x
    sta bit_mask
    lda cell_hi
    asl
    asl
    asl
    asl
    asl
    sta temp
    lda cell_lo
    lsr
    lsr
    lsr
    ora temp
    tax
    lda dirty,x
    and bit_mask
    bne !done+
    lda dirty,x
    ora bit_mask
    sta dirty,x
    inc dirty_count
    bne !done+
    inc dirty_count+1
!done:
    rts

resolve_dirty:
    lda #0
    sta coverage_ptr
    sta screen_ptr
    sta clip_lo_ptr
    sta clip_hi_ptr
    sta dirty_index
    lda #>coverage
    sta coverage_ptr+1
    lda #4
    sta screen_ptr+1
    lda #>clip_lo
    sta clip_lo_ptr+1
    lda #>clip_hi
    sta clip_hi_ptr+1
    lda #0
    sta record_ptr
    lda #$17
    sta record_ptr+1
!byte:
    ldx dirty_index
    lda dirty,x
    beq !advance+
    sta resolve_bits
    lda #0
    sta dirty,x
    ldy #0
!bit:
    lsr resolve_bits
    bcc !next_bit+
    lda (coverage_ptr),y
    tax
    lda glyph_lut,x
    sta resolved_glyph
    beq !compare+
    lda (clip_hi_ptr),y
    cmp #255
    beq !no_clip+
    ldx resolved_glyph
    lda glyph_compact,x
    clc
    adc (clip_lo_ptr),y
    sta remap_ptr
    lda (clip_hi_ptr),y
    adc #>limb_remap
    sta remap_ptr+1
    sty saved_y
    ldy #0
    lda (remap_ptr),y
    ldy saved_y
    jmp !compare+
!no_clip:
    lda resolved_glyph
!compare:
    cmp (screen_ptr),y
    beq !next_bit+
    sta resolved_glyph
    lda display_initialized
    bne !enqueue+
    lda resolved_glyph
screen_store:
    sta (screen_ptr),y
    jmp !count_store+
!enqueue:
    lda resolved_glyph
    jsr enqueue_glyph
!count_store:
    inc screen_writes
    bne !next_bit+
    inc screen_writes+1
!next_bit:
    iny
    cpy #8
    bcc !bit-
!advance:
    clc
    lda coverage_ptr
    adc #8
    sta coverage_ptr
    sta screen_ptr
    sta clip_lo_ptr
    sta clip_hi_ptr
    bcc !same_page+
    inc coverage_ptr+1
    inc screen_ptr+1
    inc clip_lo_ptr+1
    inc clip_hi_ptr+1
!same_page:
    inc dirty_index
    lda dirty_index
    cmp #125
    bcs !done+
    jmp !byte-
!done:
    rts

// Queue only final glyph changes. All comparisons/clipping stay in hidden work.
// record_ptr is the append pointer, reused after face decoding is complete.
enqueue_glyph:
    sty saved_y
    sta resolved_glyph
    tya
    clc
    adc screen_ptr
    ldy #0
    sta (record_ptr),y
    iny
    lda screen_ptr+1
    sec
    sbc #4
    sta (record_ptr),y
    iny
    lda resolved_glyph
    sta (record_ptr),y
    clc
    lda record_ptr
    adc #3
    sta record_ptr
    bcc !pointer_ready+
    inc record_ptr+1
!pointer_ready:
    lda record_ptr+1
    cmp #$19
    bcc !fits+
    beq !at_end+
    jmp queue_overflow
!at_end:
    lda record_ptr
    beq !fits+
    jmp queue_overflow
!fits:
    ldy saved_y
    rts

flush_queue:
    lda #0
    sta remap_ptr
    lda #$17
    sta remap_ptr+1
!entry:
    lda remap_ptr
    cmp record_ptr
    bne !copy+
    lda remap_ptr+1
    cmp record_ptr+1
    bne !copy+
    rts
!copy:
    ldy #0
    lda (remap_ptr),y
    sta screen_ptr
    iny
    lda (remap_ptr),y
    clc
    adc #4
    sta screen_ptr+1
    iny
    lda (remap_ptr),y
    ldy #0
visible_store:
    sta (screen_ptr),y
    clc
    lda remap_ptr
    adc #3
    sta remap_ptr
    bcc !entry-
    inc remap_ptr+1
    jmp !entry-

queue_overflow:
    brk
    jmp queue_overflow

wait_raster:
wait_boundary:
!low:
    bit $d011
    bmi !low-
!high:
    bit $d011
    bpl !high-
    rts
interrupt_return: rti
frame_index: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 4
dirty_count: .word 0
add_masks: .word 0
remove_masks: .word 0
screen_writes: .word 0
display_initialized: .byte 0
bit_masks: .byte 1,2,4,8,16,32,64,128
sample_parts:
    .for(var row=0;row<25;row++){.byte 0,8,16}
player_code_end:
.assert "Code below I/O",player_code_end<$4000,true
.align $100
raster_assets_start:
glyph_lut: .import binary "build/assets/glyph-lut.bin"
glyph_compact: .import binary "build/assets/glyph-compact.bin"
limb_remap: .import binary "build/assets/limb-remap.bin"
sample_row_lo: .import binary "build/assets/sample-row-lo.bin"
sample_row_hi: .import binary "build/assets/sample-row-hi.bin"
left_masks: .import binary "build/assets/left-masks.bin"
right_masks: .import binary "build/assets/right-masks.bin"
full_masks: .import binary "build/assets/full-masks.bin"
.align $100
clip_lo: .import binary "build/assets/clip-lo.bin"
clip_hi: .import binary "build/assets/clip-hi.bin"
animation: .import binary "build/assets/spans.sa64"
animation_end:
.label movie_counts=animation+12
.label span_pool=animation+48
.label movie_first_frame=span_pool+(movieData.get(8)&255)+256*(movieData.get(9)&255)
.assert "Limb remap aligned",<limb_remap,0
.assert "All below I/O",animation_end<=$d000,true
