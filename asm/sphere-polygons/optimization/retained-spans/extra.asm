// Retain merged white spans on the 75 native sample rows. Coordinates are
// ordered probe indices, not pixel coverage or prepared animation frames.
.const OPT_MAX_INTERVALS = 36
.label opt_current_left = $c000
.label opt_current_right = $e000
.label opt_previous_left = $ea8c
.label opt_previous_right = $f518
.label opt_current_counts = $ca8c
.label opt_previous_counts = $cad7
.assert "Retained state must not reach vectors", opt_previous_right+75*OPT_MAX_INTERVALS <= $fffa, true
.assert "At most one interval per white face", OPT_MAX_INTERVALS >= 36, true

.label opt_line = $31
.label opt_left = $32
.label opt_right = $33
.label opt_count = $34
.label opt_start = $35
.label opt_end = $36
.label opt_temp_left = $37
.label opt_temp_right = $38
.label opt_source = $39
.label opt_destination = $3a
.label opt_current_left_ptr = $3b
.label opt_current_right_ptr = $3d
.label opt_previous_left_ptr = $3f
.label opt_previous_right_ptr = $41
.label opt_current_count = $43
.label opt_previous_count = $44
.label opt_current_index = $45
.label opt_previous_index = $46
.label opt_current_inside = $47
.label opt_previous_inside = $48
.label opt_current_next = $49
.label opt_previous_next = $4a
.label opt_position = $4b
.label opt_boundary = $4c

* = $cb22 "Retained span union and delta helpers"

delta_init:
    lda #0
    ldx #0
!coverage:
    sta coverage,x
    sta coverage+$100,x
    sta coverage+$200,x
    sta coverage+$300,x
    inx
    bne !coverage-
    ldx #74
!counts:
    sta opt_current_counts,x
    sta opt_previous_counts,x
    dex
    bpl !counts-
    rts

opt_current_pointers:
    ldx opt_line
    lda opt_line_offset_lo,x
    sta opt_current_left_ptr
    sta opt_current_right_ptr
    lda opt_line_offset_hi,x
    clc
    adc #>opt_current_left
    sta opt_current_left_ptr+1
    lda opt_line_offset_hi,x
    clc
    adc #>opt_current_right
    sta opt_current_right_ptr+1
    rts

opt_all_pointers:
    jsr opt_current_pointers
    lda opt_line_offset_lo,x
    clc
    adc #<opt_previous_left
    sta opt_previous_left_ptr
    lda opt_line_offset_hi,x
    adc #>opt_previous_left
    sta opt_previous_left_ptr+1
    lda opt_line_offset_lo,x
    clc
    adc #<opt_previous_right
    sta opt_previous_right_ptr
    lda opt_line_offset_hi,x
    adc #>opt_previous_right
    sta opt_previous_right_ptr+1
    rts

opt_collect_spans:
    ldx raster_sample
    cpx raster_sample_end
    bcs !done+
    lda span_left,x
    cmp span_right,x
    bcs !next+
    stx opt_line
    lda raster_mask_bases,x
    cmp #8
    beq !middle+
    ldy span_left,x
    lda opt_first_probe3,y
    sta opt_left
    ldy span_right,x
    lda opt_first_probe3,y
    jmp !insert+
!middle:
    ldy span_left,x
    lda opt_first_probe2,y
    sta opt_left
    ldy span_right,x
    lda opt_first_probe2,y
!insert:
    sta opt_right
    cmp opt_left
    beq !next+
    jsr opt_insert_interval
!next:
    inc raster_sample
    jmp opt_collect_spans
!done:
    rts

opt_insert_interval:
    jsr opt_current_pointers
    lda opt_current_counts,x
    sta opt_count
    ldy #0
!first:
    cpy opt_count
    beq !found+
    lda (opt_current_right_ptr),y
    cmp opt_left
    bcs !found+
    iny
    bne !first-
!found:
    sty opt_start
!merge:
    cpy opt_count
    beq !merged+
    lda opt_right
    cmp (opt_current_left_ptr),y
    bcc !merged+
    lda (opt_current_left_ptr),y
    cmp opt_left
    bcs !left_ready+
    sta opt_left
!left_ready:
    lda (opt_current_right_ptr),y
    cmp opt_right
    bcc !right_ready+
    sta opt_right
!right_ready:
    iny
    bne !merge-
!merged:
    sty opt_end
    tya
    sec
    sbc opt_start
    beq !insert_new+
    cmp #1
    beq !write+
    lda opt_end
    sta opt_source
    lda opt_start
    clc
    adc #1
    sta opt_destination
!compact:
    ldy opt_source
    cpy opt_count
    beq !compacted+
    lda (opt_current_left_ptr),y
    sta opt_temp_left
    lda (opt_current_right_ptr),y
    sta opt_temp_right
    ldy opt_destination
    lda opt_temp_left
    sta (opt_current_left_ptr),y
    lda opt_temp_right
    sta (opt_current_right_ptr),y
    inc opt_source
    inc opt_destination
    bne !compact-
!compacted:
    lda opt_destination
    sta opt_count
    jmp !write+
!insert_new:
    // Every insertion came from a different white face, so the 36-slot
    // bound also covers transient unmerged spans. Trap instead of corrupting.
    lda opt_count
    cmp #OPT_MAX_INTERVALS
    bcc !capacity+
    brk
!capacity:
    ldy opt_count
!shift:
    cpy opt_start
    beq !shifted+
    dey
    lda (opt_current_left_ptr),y
    sta opt_temp_left
    lda (opt_current_right_ptr),y
    sta opt_temp_right
    iny
    lda opt_temp_left
    sta (opt_current_left_ptr),y
    lda opt_temp_right
    sta (opt_current_right_ptr),y
    dey
    bpl !shift-
!shifted:
    inc opt_count
!write:
    ldy opt_start
    lda opt_left
    sta (opt_current_left_ptr),y
    lda opt_right
    sta (opt_current_right_ptr),y
    ldx opt_line
    lda opt_count
    sta opt_current_counts,x
    rts

opt_apply_delta:
    lda #0
    sta opt_line
!line:
    jsr opt_all_pointers
    lda opt_current_counts,x
    sta opt_current_count
    lda opt_previous_counts,x
    sta opt_previous_count
    cmp opt_current_count
    bne !changed+
    tay
!compare:
    dey
    bpl !compare_entry+
    jmp !unchanged+
!compare_entry:
    lda (opt_current_left_ptr),y
    cmp (opt_previous_left_ptr),y
    bne !changed+
    lda (opt_current_right_ptr),y
    cmp (opt_previous_right_ptr),y
    beq !compare-
!changed:
    jsr opt_patch_update
    lda #0
    sta opt_current_index
    sta opt_previous_index
    sta opt_current_inside
    sta opt_previous_inside
    sta opt_position
!boundary:
    ldy opt_current_index
    cpy opt_current_count
    bcs !current_empty+
    lda opt_current_inside
    beq !current_left+
    lda (opt_current_right_ptr),y
    jmp !current_ready+
!current_left:
    lda (opt_current_left_ptr),y
    jmp !current_ready+
!current_empty:
    lda #255
!current_ready:
    sta opt_current_next
    ldy opt_previous_index
    cpy opt_previous_count
    bcs !previous_empty+
    lda opt_previous_inside
    beq !previous_left+
    lda (opt_previous_right_ptr),y
    jmp !previous_ready+
!previous_left:
    lda (opt_previous_left_ptr),y
    jmp !previous_ready+
!previous_empty:
    lda #255
!previous_ready:
    sta opt_previous_next
    cmp opt_current_next
    bcc !minimum+
    lda opt_current_next
!minimum:
    cmp #255
    beq !copy+
    sta opt_boundary
    lda opt_current_inside
    eor opt_previous_inside
    beq !toggle+
    lda opt_position
    cmp opt_boundary
    bcs !toggle+
    jsr opt_update_probes
!toggle:
    lda opt_boundary
    sta opt_position
    cmp opt_current_next
    bne !previous_toggle+
    lda opt_current_inside
    eor #1
    sta opt_current_inside
    bne !previous_toggle+
    inc opt_current_index
!previous_toggle:
    lda opt_boundary
    cmp opt_previous_next
    bne !continue+
    lda opt_previous_inside
    eor #1
    sta opt_previous_inside
    bne !continue+
    inc opt_previous_index
!continue:
    jmp !boundary-
!copy:
    ldy opt_current_count
!copy_entry:
    dey
    bmi !copied+
    lda (opt_current_left_ptr),y
    sta (opt_previous_left_ptr),y
    lda (opt_current_right_ptr),y
    sta (opt_previous_right_ptr),y
    bpl !copy_entry-
!copied:
    ldx opt_line
    lda opt_current_count
    sta opt_previous_counts,x
!unchanged:
    inc opt_line
    lda opt_line
    cmp #75
    beq !done+
    jmp !line-
!done:
    rts

opt_patch_update:
    ldx opt_line
    lda opt_coverage_row_lo,x
    sta opt_update_memory+1
    sta opt_update_store+1
    lda opt_coverage_row_hi,x
    sta opt_update_memory+2
    sta opt_update_store+2
    lda raster_mask_bases,x
    cmp #8
    beq !middle+
    lda #<opt_probe_char3
    sta opt_update_char+1
    lda #>opt_probe_char3
    sta opt_update_char+2
    lda raster_mask_bases,x
    beq !top+
    lda #<opt_probe_bit_bottom
    sta opt_update_bits+1
    lda #>opt_probe_bit_bottom
    jmp !bits_high+
!top:
    lda #<opt_probe_bit_top
    sta opt_update_bits+1
    lda #>opt_probe_bit_top
    jmp !bits_high+
!middle:
    lda #<opt_probe_char2
    sta opt_update_char+1
    lda #>opt_probe_char2
    sta opt_update_char+2
    lda #<opt_probe_bit_middle
    sta opt_update_bits+1
    lda #>opt_probe_bit_middle
!bits_high:
    sta opt_update_bits+2
    rts

opt_update_probes:
    lda opt_current_inside
    beq !clear+
    lda #$1d                       // ORA absolute,X
    sta opt_update_memory
    lda #0
    beq !operation+
!clear:
    lda #$3d                       // AND absolute,X
    sta opt_update_memory
    lda #255
!operation:
    sta opt_update_inverse+1
    ldy opt_position
!probe:
opt_update_char:
    ldx opt_probe_char3,y
opt_update_bits:
    lda opt_probe_bit_top,y
opt_update_inverse:
    eor #0
opt_update_memory:
    ora $1000,x
opt_update_store:
    sta $1000,x
    iny
    cpy opt_boundary
    bcc !probe-
    rts

opt_helpers_end:
.assert "Helper code below I/O", opt_helpers_end <= $d000, true
