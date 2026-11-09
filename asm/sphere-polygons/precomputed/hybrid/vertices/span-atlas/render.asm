render_polygons:
clear_start:
    lda #0
    ldx #0
!clear:
    sta coverage,x
    sta coverage+$100,x
    sta coverage+$200,x
    sta coverage+$300,x
    inx
    bne !clear-
clear_end:
    nop
    lda #0
    sta current_face_index
!face:
    ldx current_face_index
    txa
    and #7
    tay
    lda bit_masks,y
    sta visible_bits
    txa
    lsr
    lsr
    lsr
    tay
    lda visible_faces,y
    and visible_bits
    beq !next+
    lda movie_counts,x
    sta raster_vertex_count
face_edges_start:
    jsr decode_face_spans
face_edges_end:
    nop
face_fill_start:
    lda raster_sample
    cmp raster_sample_end
    beq !filled+
    jsr raster_fill_span
!filled:
face_fill_end:
    nop
!next:
    inc current_face_index
    lda current_face_index
    cmp #36
    bcc !face-
    rts
