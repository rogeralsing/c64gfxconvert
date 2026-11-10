// Character codes are the eight-bit coverage masks themselves. The existing
// OR fill therefore writes directly to the hidden screen, without a resolve.
render_polygons:
clear_start:
    lda back_screen_hi
    sta raster_clear0+2
    clc
    adc #1
    sta raster_clear1+2
    adc #1
    sta raster_clear2+2
    adc #1
    sta raster_clear3+2
    lda #0
    ldx #0
!clear:
raster_clear0:
    sta $0400,x
raster_clear1:
    sta $0500,x
raster_clear2:
    sta $0600,x
raster_clear3:
    sta $0700,x
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
