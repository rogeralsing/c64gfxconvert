// Exact per-edge sample crossings. Existing bounds/face/OR semantics remain.
// Four-byte records: first sample, first X, LE16 normalized-pattern offset.
raster_edge:
    ldy #0
    lda (atlas_record_ptr),y
    sta raster_edge_sample
    iny
    lda (atlas_record_ptr),y
    sta raster_x0
    iny
    lda (atlas_record_ptr),y
    clc
    adc #<atlas_pool
    sta raster_ratio_ptr
    iny
    lda (atlas_record_ptr),y
    adc #>atlas_pool
    sta raster_ratio_ptr+1
    clc
    lda atlas_record_ptr
    adc #4
    sta atlas_record_ptr
    bcc !record_ready+
    inc atlas_record_ptr+1
!record_ready:
    ldy #0
    lda (raster_ratio_ptr),y
    sta raster_edge_end
    bne !active+
    rts
!active:
    ldx raster_edge_sample
    lda raster_x0
!sample:
    cmp span_left,x
    bcs !not_left+
    sta span_left,x
!not_left:
    cmp span_right,x
    bcc !not_right+
    sta span_right,x
!not_right:
    dec raster_edge_end
    bne !next+
    rts
!next:
    iny
    lda (raster_ratio_ptr),y
    clc
    adc raster_x0
    inx
    jmp !sample-
