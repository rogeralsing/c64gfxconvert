// Per-white-face retained probe spans with byte contribution counts. The
// sample domain is 25 character columns, not a high-resolution pixel bitmap.
.label opt_history_left = $c000
.label opt_history_right = $f388
.label opt_counts = $e000
.label opt_previous_first = $ca8c
.label opt_previous_end = $cab0
.label opt_previous_model = $cad4
.assert "History below vectors", opt_history_right+36*75 <= $fffa, true
.assert "Contribution counts before right history", opt_counts+5000 <= opt_history_right, true

* = $cb22 "Retained face spans and contribution-count helpers"

delta_init:
    lda model
    sta opt_previous_model
    jmp opt_reset

opt_reset:
    lda #0
    ldx #0
!coverage:
    sta coverage,x
    sta coverage+$100,x
    sta coverage+$200,x
    sta coverage+$300,x
    inx
    bne !coverage-
!count_pages:
    .for(var page=0;page<19;page++) { sta opt_counts+page*$100,x }
    inx
    bne !count_pages-
    ldx #0
!count_tail:
    sta opt_counts+$1300,x
    inx
    cpx #$88
    bcc !count_tail-
    ldx #35
!bounds:
    sta opt_previous_first,x
    sta opt_previous_end,x
    dex
    bpl !bounds-
    rts

opt_empty_face:
    lda #0
    sta opt_new_first
    sta opt_new_end
    // Stable white-face slots advance even for back-facing or empty faces.
opt_process_face:
    ldx opt_white_slot
    cpx #36
    bcc !slot_ok+
    brk
!slot_ok:
    lda opt_history_lo,x
    sta opt_left_ptr
    clc
    adc #<opt_history_right
    sta opt_right_ptr
    lda opt_history_hi,x
    adc #>opt_history_right
    sta opt_right_ptr+1
    lda opt_history_hi,x
    clc
    adc #>opt_history_left
    sta opt_left_ptr+1
    lda opt_previous_first,x
    sta opt_old_first
    lda opt_previous_end,x
    sta opt_old_end
    lda opt_new_first
    sta opt_previous_first,x
    lda opt_new_end
    sta opt_previous_end,x

    lda opt_old_end
    beq !old_empty+
    lda opt_new_end
    beq !new_empty+
    cmp opt_old_end
    bcs !end_ready+
    lda opt_old_end
!end_ready:
    sta opt_line_end
    lda opt_new_first
    cmp opt_old_first
    bcc !first_ready+
    lda opt_old_first
!first_ready:
    sta opt_line
    jmp !line+
!old_empty:
    lda opt_new_end
    bne !new_present+
    rts
!new_present:
    sta opt_line_end
    lda opt_new_first
    sta opt_line
    jmp !line+
!new_empty:
    lda opt_old_end
    sta opt_line_end
    lda opt_old_first
    sta opt_line

!line:
    ldy opt_line
    cpy opt_old_first
    bcc !no_old+
    cpy opt_old_end
    bcs !no_old+
    lda (opt_left_ptr),y
    sta opt_old_left
    lda (opt_right_ptr),y
    sta opt_old_right
    jmp !old_ready+
!no_old:
    lda #0
    sta opt_old_left
    sta opt_old_right
!old_ready:
    ldx opt_line
    cpx opt_new_first
    bcc !no_new+
    cpx opt_new_end
    bcs !no_new+
    lda span_left,x
    cmp span_right,x
    bcs !no_new+
    lda raster_mask_bases,x
    cmp #8
    beq !middle+
    ldy span_left,x
    lda opt_first_probe3,y
    sta opt_new_left
    ldy span_right,x
    lda opt_first_probe3,y
    jmp !new_ready+
!middle:
    ldy span_left,x
    lda opt_first_probe2,y
    sta opt_new_left
    ldy span_right,x
    lda opt_first_probe2,y
    jmp !new_ready+
!no_new:
    lda #0
    sta opt_new_left
!new_ready:
    sta opt_new_right
    // Equal endpoints denote an empty interval, including spans too narrow
    // to contain a native probe. Canonicalize them before set subtraction.
    cmp opt_new_left
    bne !canonical+
    lda #0
    sta opt_new_left
    sta opt_new_right
!canonical:
    ldy opt_line
    lda opt_new_left
    sta (opt_left_ptr),y
    lda opt_new_right
    sta (opt_right_ptr),y
    lda opt_new_left
    cmp opt_old_left
    bne !changed+
    lda opt_new_right
    cmp opt_old_right
    beq !next+
!changed:
    jsr opt_patch_line
    // Empty and disjoint intervals must not form phantom overlap bands.
    lda opt_old_left
    cmp opt_old_right
    beq !add_whole+
    lda opt_new_left
    cmp opt_new_right
    beq !remove_whole+
    lda opt_old_right
    cmp opt_new_left
    bcc !disjoint+
    beq !disjoint+
    lda opt_new_right
    cmp opt_old_left
    bcc !disjoint+
    beq !disjoint+

    lda opt_old_left
    sta opt_band_left
    lda opt_new_left
    sta opt_band_right
    jsr opt_remove_band
    lda opt_new_right
    sta opt_band_left
    lda opt_old_right
    sta opt_band_right
    jsr opt_remove_band
    lda opt_new_left
    sta opt_band_left
    lda opt_old_left
    sta opt_band_right
    jsr opt_add_band
    lda opt_old_right
    sta opt_band_left
    lda opt_new_right
    sta opt_band_right
    jsr opt_add_band
    jmp !next+
!disjoint:
    jsr opt_remove_whole
    jsr opt_add_whole
    jmp !next+
!remove_whole:
    jsr opt_remove_whole
    jmp !next+
!add_whole:
    jsr opt_add_whole
!next:
    inc opt_line
    lda opt_line
    cmp opt_line_end
    beq !done+
    jmp !line-
!done:
    rts

opt_remove_whole:
    lda opt_old_left
    sta opt_band_left
    lda opt_old_right
    sta opt_band_right
    jmp opt_remove_band
opt_add_whole:
    lda opt_new_left
    sta opt_band_left
    lda opt_new_right
    sta opt_band_right
    jmp opt_add_band

opt_patch_line:
    ldx opt_line
    lda opt_count_row_lo,x
    sta opt_count_change+1
    sta opt_count_read+1
    lda opt_count_row_hi,x
    sta opt_count_change+2
    sta opt_count_read+2
    lda opt_coverage_row_lo,x
    sta opt_coverage_read+1
    sta opt_coverage_store+1
    lda opt_coverage_row_hi,x
    sta opt_coverage_read+2
    sta opt_coverage_store+2
    lda raster_mask_bases,x
    cmp #8
    beq !middle+
    lda #21
    sta opt_min_probe+1
    lda #96
    sta opt_max_probe+1
    lda #<opt_probe_local3
    sta opt_local_read+1
    lda #>opt_probe_local3
    sta opt_local_read+2
    lda #<opt_probe_char3
    sta opt_char_read+1
    lda #>opt_probe_char3
    sta opt_char_read+2
    lda raster_mask_bases,x
    beq !top+
    lda #<opt_probe_bit_bottom
    sta opt_bit_read+1
    lda #>opt_probe_bit_bottom
    jmp !bits_high+
!top:
    lda #<opt_probe_bit_top
    sta opt_bit_read+1
    lda #>opt_probe_bit_top
    jmp !bits_high+
!middle:
    lda #14
    sta opt_min_probe+1
    lda #64
    sta opt_max_probe+1
    lda #<opt_probe_local2
    sta opt_local_read+1
    lda #>opt_probe_local2
    sta opt_local_read+2
    lda #<opt_probe_char2
    sta opt_char_read+1
    lda #>opt_probe_char2
    sta opt_char_read+2
    lda #<opt_probe_bit_middle
    sta opt_bit_read+1
    lda #>opt_probe_bit_middle
!bits_high:
    sta opt_bit_read+2
    rts

opt_remove_band:
    lda opt_band_left
    cmp opt_band_right
    bcs opt_empty_band
    lda #$de                       // DEC absolute,X
    sta opt_count_change
    lda #0
    sta opt_transition+1
    lda #$3d                       // AND absolute,X
    sta opt_coverage_read
    lda #255
    jmp opt_update_band
opt_add_band:
    lda opt_band_left
    cmp opt_band_right
    bcs opt_empty_band
    lda #$fe                       // INC absolute,X
    sta opt_count_change
    lda #1
    sta opt_transition+1
    lda #$1d                       // ORA absolute,X
    sta opt_coverage_read
    lda #0
opt_update_band:
    sta opt_inverse+1
    lda opt_band_left
opt_min_probe:
    cmp #21
    bcc opt_invalid_count
    lda opt_band_right
opt_max_probe:
    cmp #96
    bcc !range_ok+
    bne opt_invalid_count
!range_ok:
    ldy opt_band_left
!probe:
opt_local_read:
    ldx opt_probe_local3,y
opt_count_change:
    inc $e000,x
opt_count_read:
    lda $e000,x
    cmp #37                        // Detect underflow or impossible ownership.
    bcs opt_invalid_count
opt_transition:
    cmp #1
    bne !next+
opt_char_read:
    ldx opt_probe_char3,y
opt_bit_read:
    lda opt_probe_bit_top,y
opt_inverse:
    eor #0
opt_coverage_read:
    ora $1000,x
opt_coverage_store:
    sta $1000,x
!next:
    iny
    cpy opt_band_right
    bcc !probe-
opt_empty_band:
    rts
opt_invalid_count:
    brk
    jmp opt_invalid_count

opt_helpers_end:
.assert "Helpers below I/O", opt_helpers_end <= $d000, true
