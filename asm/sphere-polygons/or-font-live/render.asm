// Convex polygons become character-row sample spans. No source bitmap is built.
.label coverage = $1000
.label projected_x = $1400
.label projected_y = $1440
.label span_left = $1480
.label span_right = $1500

.label raster_ratio_ptr = $02
.label face_ptr = $04
.label raster_cover_ptr = $06
.label raster_clip_ptr = $08
.label raster_screen_ptr = $0a
.label raster_remap_ptr = $0c
.label raster_faces_left = $0e
.label raster_vertex_count = $0f
.label raster_edge_index = $10
.label raster_min_y = $11
.label raster_max_y = $12
.label raster_first = $13
.label raster_sample_end = $14
.label raster_sample = $15
.label raster_edge_first = $16
.label raster_edge_end = $17
.label raster_edge_sample = $18
.label raster_x0 = $19
.label raster_y0 = $1a
.label raster_x1 = $1b
.label raster_y1 = $1c
.label raster_dx = $1d
.label raster_dy = $1e
.label raster_negative = $1f
.label raster_q = $20
.label raster_r = $21
.label raster_x = $22
.label raster_error = $23
.label raster_q2 = $24
.label raster_q3 = $25
.label raster_r2 = $26
.label raster_r3 = $27
.label raster_step_q = $28
.label raster_step_r = $29
.label raster_left_col = $2a
.label raster_right_col = $2b
.label raster_left_mask = $2c
.label raster_right_mask = $2d
.label raster_row_mask = $2e
.label raster_mask_part = $2f
.label raster_clip_left = $30

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
    lda faces_base
    sta face_ptr
    lda faces_base+1
    sta face_ptr+1
    lda face_count
    sta raster_faces_left
!face:
    ldy #1
    lda (face_ptr),y
    beq !next+
    jsr face_front
    beq !next+
    jsr raster_face
!next:
    clc
    lda face_ptr
    adc #12
    sta face_ptr
    bcc !face_pointer+
    inc face_ptr+1
!face_pointer:
    dec raster_faces_left
    bne !face-
    rts

raster_face:
    ldy #0
    lda (face_ptr),y
    sta raster_vertex_count
    lda #255
    sta raster_min_y
    lda #0
    sta raster_max_y
    sta raster_edge_index
!bounds:
    lda raster_edge_index
    clc
    adc #5
    tay
    lda (face_ptr),y
    tax
    lda projected_y,x
    cmp raster_min_y
    bcs !not_min+
    sta raster_min_y
!not_min:
    cmp raster_max_y
    bcc !not_max+
    sta raster_max_y
!not_max:
    inc raster_edge_index
    lda raster_edge_index
    cmp raster_vertex_count
    bcc !bounds-
    ldx raster_min_y
    lda first_sample,x
    sta raster_first
    ldx raster_max_y
    lda first_sample,x
    sta raster_sample_end
    cmp raster_first
    bne !has_samples+
    rts
!has_samples:
    ldx raster_first
!clear_bounds:
    lda #255
    sta span_left,x
    lda #0
    sta span_right,x
    inx
    cpx raster_sample_end
    bcc !clear_bounds-
    lda #0
    sta raster_edge_index
face_edges_start:
!edge:
    jsr raster_edge
    inc raster_edge_index
    lda raster_edge_index
    cmp raster_vertex_count
    bcc !edge-
face_edges_end:
    lda raster_first
    sta raster_sample
face_fill_start:
    jmp raster_fill_span

raster_edge:
    lda raster_edge_index
    clc
    adc #5
    tay
    lda (face_ptr),y
    tax
    lda projected_x,x
    sta raster_x0
    lda projected_y,x
    sta raster_y0
    lda raster_edge_index
    clc
    adc #1
    cmp raster_vertex_count
    bcc !not_last+
    lda #0
!not_last:
    clc
    adc #5
    tay
    lda (face_ptr),y
    tax
    lda projected_x,x
    sta raster_x1
    lda projected_y,x
    sta raster_y1
    cmp raster_y0
    bne !not_horizontal+
    rts
!not_horizontal:
    bcs !ordered+
    ldx raster_x0
    lda raster_x1
    sta raster_x0
    stx raster_x1
    ldx raster_y0
    lda raster_y1
    sta raster_y0
    stx raster_y1
!ordered:
    lda raster_y1
    sec
    sbc raster_y0
    sta raster_dy
    lda raster_x1
    sec
    sbc raster_x0
    bcs !positive+
    eor #255
    clc
    adc #1
    sta raster_dx
    lda #1
    bne !direction+
!positive:
    sta raster_dx
    lda #0
!direction:
    sta raster_negative
    ldx raster_y0
    lda first_sample,x
    sta raster_edge_first
    sta raster_edge_sample
    ldx raster_y1
    lda first_sample,x
    sta raster_edge_end
    cmp raster_edge_first
    bne !active+
    rts
!active:
    ldx raster_dy
    lda ratio_row_lo,x
    sta raster_ratio_ptr
    lda ratio_row_hi,x
    clc
    adc #>ratio_q
    sta raster_ratio_ptr+1
    ldy raster_dx
    lda (raster_ratio_ptr),y
    sta raster_q
    asl
    sta raster_q2
    clc
    adc raster_q
    sta raster_q3
    lda ratio_row_hi,x
    clc
    adc #>ratio_r
    sta raster_ratio_ptr+1
    lda (raster_ratio_ptr),y
    sta raster_r
    asl
    sta raster_r2
    clc
    adc raster_r
    sta raster_r3
    lda raster_x0
    sta raster_x
    lda #0
    sta raster_error
    ldx raster_edge_first
    lda sample_y,x
    sec
    sbc raster_y0
    beq !sample+
    jsr raster_advance
!sample:
    lda raster_x
    ldx raster_negative
    bne !ceil_ready+
    ldx raster_error
    beq !ceil_ready+
    clc
    adc #1
!ceil_ready:
    ldx raster_edge_sample
    cmp span_left,x
    bcs !not_left+
    sta span_left,x
!not_left:
    cmp span_right,x
    bcc !not_right+
    sta span_right,x
!not_right:
    lda sample_gap,x
    inc raster_edge_sample
    ldx raster_edge_sample
    cpx raster_edge_end
    bcc !advance+
    rts
!advance:
    jsr raster_advance
    jmp !sample-

// Advance directly by the 1/2/3-unit sample gap, then normalize the remainder.
raster_advance:
    cmp #2
    beq !two+
    cmp #3
    beq !three+
    lda raster_q
    sta raster_step_q
    lda raster_r
    jmp !have_r+
!two:
    lda raster_q2
    sta raster_step_q
    lda raster_r2
    jmp !have_r+
!three:
    lda raster_q3
    sta raster_step_q
    lda raster_r3
!have_r:
    sta raster_step_r
    lda raster_negative
    beq !positive+
    lda raster_x
    sec
    sbc raster_step_q
    jmp !have_x+
!positive:
    lda raster_x
    clc
    adc raster_step_q
!have_x:
    sta raster_x
    lda raster_error
    clc
    adc raster_step_r
    sta raster_error
!normalize:
    lda raster_error
    cmp raster_dy
    bcc !done+
    sec
    sbc raster_dy
    sta raster_error
    lda raster_negative
    beq !increment+
    dec raster_x
    jmp !normalize-
!increment:
    inc raster_x
    jmp !normalize-
!done:
    rts

raster_fill_span:
    ldx raster_sample
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
    lda sample_row_lo,x
    sta raster_cover_ptr
    lda sample_row_hi,x
    clc
    adc back_screen_hi
    sta raster_cover_ptr+1
    lda raster_mask_bases,x
    sta raster_mask_part
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
    lda raster_mask_part
    lsr
    lsr
    lsr
    tay
    lda full_masks,y
    sta raster_row_mask
    lda raster_left_col
    cmp raster_right_col
    bne !multiple+
    lda raster_left_mask
    and raster_right_mask
    beq raster_next_sample
    ldy raster_left_col
    ora (raster_cover_ptr),y
    sta (raster_cover_ptr),y
    jmp raster_next_sample
!multiple:
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
    lda raster_row_mask
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
    lda raster_sample
    cmp raster_sample_end
    bcs !done+
    jmp raster_fill_span
!done:
face_fill_end:
    rts
