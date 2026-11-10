// Precomputed individual edge paths; aggregate crossings per face on the C64.
// This format retains edge work separately from final left/right face spans.
* = $e000 "Precomputed-edge crossing preparation"

prepare_source:
    rts

prepare_face:
    jsr read_source
    sta first_sample
    jsr read_source
    clc
    adc first_sample
    sta end_sample
    jsr read_source
    sta path_edges_left
    ldx first_sample
    cpx end_sample
    bcs !cleared+
!clear:
    lda #40
    sta span_left_col,x
    lda #0
    sta span_right_col,x
    sta span_left_frac,x
    sta span_right_frac,x
    inx
    cpx end_sample
    bne !clear-
!cleared:
    lda path_edges_left
    bne path_next_edge
    rts

path_next_edge:
    jsr read_source
    sta path_sample
    jsr read_source
    clc
    adc path_sample
    sta path_end
    jsr read_source
    sta path_x
    jsr read_source
    sta path_x+1
path_sample_loop:
    lda path_x
    and #7
    sta path_fraction
    lda path_x
    lsr
    lsr
    lsr
    sta path_column
    lda path_x+1
    beq !column_ready+
    lda path_column
    ora #32
    sta path_column
!column_ready:
    ldx path_sample
    lda path_column
    cmp span_left_col,x
    bcc !left+
    bne !test_right+
    lda path_fraction
    cmp span_left_frac,x
    bcs !test_right+
!left:
    lda path_column
    sta span_left_col,x
    lda path_fraction
    sta span_left_frac,x
!test_right:
    lda path_column
    cmp span_right_col,x
    bcc !aggregated+
    bne !right+
    lda path_fraction
    cmp span_right_frac,x
    bcc !aggregated+
!right:
    lda path_column
    sta span_right_col,x
    lda path_fraction
    sta span_right_frac,x
!aggregated:
    inc path_sample
    lda path_sample
    cmp path_end
    bcs !edge_done+
    jsr read_source
    sta path_delta
    ldx #0
    cmp #128
    bcc !sign+
    dex
!sign:
    txa
    sta path_sign
    clc
    lda path_x
    adc path_delta
    sta path_x
    lda path_x+1
    adc path_sign
    sta path_x+1
    jmp path_sample_loop
!edge_done:
    dec path_edges_left
    beq !done+
    jmp path_next_edge
!done:
    rts

path_edges_left: .byte 0
path_sample: .byte 0
path_end: .byte 0
path_x: .word 0
path_column: .byte 0
path_fraction: .byte 0
path_delta: .byte 0
path_sign: .byte 0
edge_code_end:
.assert "Precomputed edge code stays below vectors", edge_code_end <= $ff00, true
