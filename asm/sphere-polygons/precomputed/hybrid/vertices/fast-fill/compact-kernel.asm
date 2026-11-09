// Drop-in replacement for raster_fill_span through raster_next_sample.
// Existing ABI: raster_sample/raster_sample_end, span_left/right and mask tables.
// Preserves byte-exact OR composition, including shared polygon edge cells.
raster_fill_span:
    ldx raster_sample
    lda sample_row_lo,x
    sta raster_cover_ptr
    lda sample_row_hi,x
    clc
    adc #>coverage
    sta raster_cover_ptr+1
    lda raster_mask_bases,x
    sta raster_mask_part
fast_fill_sample:
    lda span_left,x
    cmp span_right,x
    bcc !nonempty+
    jmp raster_next_sample
!nonempty:
    lsr
    lsr
    lsr
    sta raster_left_col
    lda span_right,x
    lsr
    lsr
    lsr
    sta raster_right_col
    lda span_left,x
    and #7
    ora raster_mask_part
    tay
    lda left_masks,y
    sta raster_left_mask
    lda span_right,x
    and #7
    ora raster_mask_part
    tay
    lda right_masks,y
    sta raster_right_mask
    lda raster_left_col
    cmp raster_right_col
    bne !multiple+
    lda raster_left_mask
    and raster_right_mask
    beq raster_next_sample
    sta raster_left_mask
    ldy raster_left_col
    lda raster_left_mask
    ora (raster_cover_ptr),y
    sta (raster_cover_ptr),y
    jmp raster_next_sample
!multiple:
    lda fast_fill_full_masks,x
    tax
    ldy raster_left_col
    lda raster_left_mask
    beq !interior_start+
    ora (raster_cover_ptr),y
    sta (raster_cover_ptr),y
!interior_start:
    iny
    cpy raster_right_col
    bcs !right+
!interior:
    txa
    ora (raster_cover_ptr),y
    sta (raster_cover_ptr),y
    iny
    cpy raster_right_col
    bcc !interior-
!right:
    lda raster_right_mask
    beq raster_next_sample
    ora (raster_cover_ptr),y
    sta (raster_cover_ptr),y
raster_next_sample:
    inc raster_sample
    ldx raster_sample
    cpx raster_sample_end
    bcs !done+
    lda raster_mask_bases,x
    sta raster_mask_part
    beq !next_row+
    jmp fast_fill_sample
!next_row:
    clc
    lda raster_cover_ptr
    adc #40
    sta raster_cover_ptr
    bcc !row_ready+
    inc raster_cover_ptr+1
!row_ready:
    jmp fast_fill_sample
!done:
    rts

fast_fill_full_masks:
    .for (var row = 0; row < 25; row++) {
        .byte $07,$18,$e0
    }
