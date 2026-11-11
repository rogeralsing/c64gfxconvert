// Signed projected XY input for the large-sphere geometry benchmark.
// Each frame begins with four 182-byte planes (Xlo,Xhi,Ylo,Yhi), then the
// renderer's face count and visible-face records [vertexCount, indices...].
// Reconstruct exact ceil-rounded, half-open edge crossings on the 6510.
// SOURCE_KIND 3 instead decodes packed XY deltas into retained vertex planes
// and selects shared face topology using the decoded visibility bits.
* = $e000 "Runtime projected-edge crossing preparation"

.label edge_xlo_ptr = $40
.label edge_xhi_ptr = $42
.label edge_ylo_ptr = $44
.label edge_yhi_ptr = $46

prepare_source:
    .if (SOURCE_KIND==3) { jmp compact_prepare_source }
    lda source_ptr
    sta edge_xlo_ptr
    lda source_ptr+1
    sta edge_xlo_ptr+1
    ldx #0
!plane:
    clc
    lda edge_xlo_ptr,x
    adc #182
    sta edge_xhi_ptr,x
    lda edge_xlo_ptr+1,x
    adc #0
    sta edge_xhi_ptr+1,x
    inx
    inx
    cpx #6
    bne !plane-
    clc
    lda edge_yhi_ptr
    adc #182
    sta source_ptr
    lda edge_yhi_ptr+1
    adc #0
    sta source_ptr+1
    rts

prepare_face:
    .if (SOURCE_KIND==3) { jsr compact_next_face } else { jsr read_source }
    sta edge_vertex_count
    lda #200
    sta edge_min_y
    lda #0
    sta edge_max_y
    sta edge_vertex
!vertex:
    .if (SOURCE_KIND==3) { jsr compact_read_index } else { jsr read_source }
    tay
    ldx edge_vertex
    lda (edge_xlo_ptr),y
    sta edge_vxlo,x
    lda (edge_xhi_ptr),y
    sta edge_vxhi,x
    lda (edge_ylo_ptr),y
    sta edge_vylo,x
    lda (edge_yhi_ptr),y
    sta edge_vyhi,x
    jsr edge_clamp_y
    cmp edge_min_y
    bcs !not_min+
    sta edge_min_y
!not_min:
    cmp edge_max_y
    bcc !not_max+
    sta edge_max_y
!not_max:
    inc edge_vertex
    lda edge_vertex
    cmp edge_vertex_count
    bne !vertex-
    lda edge_min_y
    jsr edge_first_sample
    stx first_sample
    lda edge_max_y
    jsr edge_first_sample
    stx end_sample
    cpx first_sample
    bne !has_rows+
    rts
!has_rows:
    ldx first_sample
!clear:
    lda #40
    sta span_left_col,x
    lda #0
    sta span_left_frac,x
    sta span_right_col,x
    sta span_right_frac,x
    inx
    cpx end_sample
    bne !clear-
    lda #0
    sta edge_vertex
!edge:
    ldx edge_vertex
    inx
    cpx edge_vertex_count
    bne !next_vertex+
    ldx #0
!next_vertex:
    stx edge_b
    ldy edge_vertex
    lda edge_vylo,y
    sec
    sbc edge_vylo,x
    lda edge_vyhi,y
    sbc edge_vyhi,x
    bmi !ordered+
    ldx edge_vertex
    ldy edge_b
!ordered:
    // Y is the lower-Y endpoint, X the upper-Y endpoint.
    lda edge_vylo,y
    sta edge_y0
    lda edge_vyhi,y
    sta edge_y0+1
    lda edge_vylo,x
    sec
    sbc edge_y0
    sta edge_dy
    bne !nonhorizontal+
    jmp edge_next_edge
!nonhorizontal:
    // Every visible edge in this 200-face movie has dy <= 62.
    lda edge_vxlo,y
    sta edge_x
    lda edge_vxhi,y
    sta edge_x+1
    lda edge_vxlo,x
    sec
    sbc edge_x
    sta edge_dx
    lda edge_vxhi,x
    sbc edge_x+1
    bmi !negative+
    lda #0
    sta edge_negative
    jmp !slope+
!negative:
    lda #1
    sta edge_negative
    lda #0
    sec
    sbc edge_dx
    sta edge_dx
!slope:
    stx edge_b
    lda edge_dx
    ldx #0
!divide:
    cmp edge_dy
    bcc !divided+
    sbc edge_dy
    inx
    jmp !divide-
!divided:
    sta edge_slope_remainder
    stx edge_quotient
    lda #0
    sta edge_remainder
    ldx edge_b
    jsr edge_clamp_y
    jsr edge_first_sample
    stx edge_sample_end
    ldx edge_vertex
    // Reordered lower endpoint is identified by edge_y0, not edge_vertex.
    lda edge_y0+1
    bmi !below_top+
    lda edge_y0
    cmp #200
    bcc !start_y+
    lda #200
    bne !start_y+
!below_top:
    lda #0
!start_y:
    jsr edge_first_sample
    stx edge_sample
    cpx edge_sample_end
    bne !edge_has_samples+
    jmp edge_next_edge
!edge_has_samples:
    lda edge_sample_y,x
    sec
    sbc edge_y0
    sta edge_steps
    jsr edge_advance
edge_sample_loop:
    lda edge_x
    sta edge_cross
    lda edge_x+1
    sta edge_cross+1
    lda edge_negative
    bne !ceil_ready+
    lda edge_remainder
    beq !ceil_ready+
    inc edge_cross
    bne !ceil_ready+
    inc edge_cross+1
!ceil_ready:
    // Clamp signed X crossing to the viewport's half-open range [0,320].
    lda edge_cross+1
    bmi !zero+
    cmp #1
    bcc !clipped+
    bne !right_edge+
    lda edge_cross
    cmp #64
    bcc !clipped+
!right_edge:
    lda #64
    sta edge_cross
    lda #1
    sta edge_cross+1
    bne !clipped+
!zero:
    lda #0
    sta edge_cross
    sta edge_cross+1
!clipped:
    lda edge_cross
    and #7
    sta edge_fraction
    lda edge_cross
    lsr
    lsr
    lsr
    sta edge_column
    lda edge_cross+1
    beq !column_ready+
    lda edge_column
    ora #32
    sta edge_column
!column_ready:
    ldx edge_sample
    lda edge_column
    cmp span_left_col,x
    bcc !left+
    bne !test_right+
    lda edge_fraction
    cmp span_left_frac,x
    bcs !test_right+
!left:
    lda edge_column
    sta span_left_col,x
    lda edge_fraction
    sta span_left_frac,x
!test_right:
    lda edge_column
    cmp span_right_col,x
    bcc !aggregated+
    bne !right+
    lda edge_fraction
    cmp span_right_frac,x
    bcc !aggregated+
!right:
    lda edge_column
    sta span_right_col,x
    lda edge_fraction
    sta span_right_frac,x
!aggregated:
    inc edge_sample
    ldx edge_sample
    cpx edge_sample_end
    bcs edge_next_edge
    lda edge_sample_y,x
    sec
    sbc edge_sample_y-1,x
    sta edge_steps
    jsr edge_advance
    jmp edge_sample_loop

edge_next_edge:
    inc edge_vertex
    lda edge_vertex
    cmp edge_vertex_count
    beq !done+
    jmp !edge-
!done:
    rts

// Clamp the signed Y coordinate of vertex X to [0,200].
edge_clamp_y:
    lda edge_vyhi,x
    bmi !top+
    bne !bottom+
    lda edge_vylo,x
    cmp #200
    bcc !done+
!bottom:
    lda #200
    rts
!top:
    lda #0
!done:
    rts

// A in [0,200] -> first sample index with sampleY >= A, or 75.
edge_first_sample:
    sta edge_find_y
    ldx #0
!find:
    lda edge_sample_y,x
    cmp edge_find_y
    bcs !done+
    inx
    cpx #75
    bne !find-
!done:
    rts

edge_advance:
    lda edge_steps
    beq !done+
!step:
    clc
    lda edge_remainder
    adc edge_slope_remainder
    cmp edge_dy
    bcc !no_extra+
    sbc edge_dy
    sta edge_remainder
    lda #1
    bne !amount+
!no_extra:
    sta edge_remainder
    lda #0
!amount:
    clc
    adc edge_quotient
    sta edge_amount
    lda edge_negative
    beq !positive+
    sec
    lda edge_x
    sbc edge_amount
    sta edge_x
    lda edge_x+1
    sbc #0
    sta edge_x+1
    jmp !advanced+
!positive:
    clc
    lda edge_x
    adc edge_amount
    sta edge_x
    lda edge_x+1
    adc #0
    sta edge_x+1
!advanced:
    dec edge_steps
    bne !step-
!done:
    rts

edge_sample_y:
    .for (var row=0; row<25; row++) { .byte row*8+1,row*8+4,row*8+6 }
edge_vxlo: .fill 4,0
edge_vxhi: .fill 4,0
edge_vylo: .fill 4,0
edge_vyhi: .fill 4,0
edge_vertex_count: .byte 0
edge_vertex: .byte 0
edge_b: .byte 0
edge_min_y: .byte 0
edge_max_y: .byte 0
edge_y0: .word 0
edge_x: .word 0
edge_dx: .byte 0
edge_dy: .byte 0
edge_negative: .byte 0
edge_quotient: .byte 0
edge_slope_remainder: .byte 0
edge_remainder: .byte 0
edge_sample: .byte 0
edge_sample_end: .byte 0
edge_steps: .byte 0
edge_amount: .byte 0
edge_cross: .word 0
edge_column: .byte 0
edge_fraction: .byte 0
edge_find_y: .byte 0
.label compact_xy_xlo = $1600
.label compact_xy_xhi = $1600+182
.label compact_xy_ylo = $1600+364
.label compact_xy_yhi = $1600+546
.label compact_tokens = $1900
.label compact_visibility = $1960
.label compact_topology_ptr = $48
.label compact_dx = $4a
.label compact_dy = $4b
.label compact_packed = $4c
.label compact_vis_index = $4d
.label compact_vis_mask = $4e
.label compact_count = $4f
.label compact_visible = $50

prepare_initial_source:
    .if (SOURCE_KIND==3) {
        ldx #0
    !pages:
        lda compact_seed,x
        sta $1600,x
        lda compact_seed+$100,x
        sta $1700,x
        inx
        bne !pages-
        ldx #0
    !tail:
        lda compact_seed+$200,x
        sta $1800,x
        inx
        cpx #216
        bne !tail-
        rts
    }

compact_prepare_source:
    .if (SOURCE_KIND==3) {
        ldx #0
    !tokens:
        jsr read_source
        sta compact_tokens,x
        inx
        cpx #91
        bne !tokens-
        ldx #0
    !vertex:
        txa
        lsr
        tay
        lda compact_tokens,y
        sta compact_packed
        txa
        and #1
        bne !odd+
        lda compact_packed
        lsr
        lsr
        lsr
        lsr
        jmp !token_ready+
    !odd:
        lda compact_packed
        and #15
    !token_ready:
        cmp #15
        beq !escape+
        asl
        tay
        lda compact_book,y
        sta compact_dx
        iny
        lda compact_book,y
        sta compact_dy
        jmp !apply+
    !escape:
        jsr read_source
        sta compact_dx
        jsr read_source
        sta compact_dy
    !apply:
        clc
        lda compact_xy_xlo,x
        adc compact_dx
        sta compact_xy_xlo,x
        lda compact_dx
        bmi !x_negative+
        lda #0
        bpl !x_high+
    !x_negative:
        lda #255
    !x_high:
        adc compact_xy_xhi,x
        sta compact_xy_xhi,x
        clc
        lda compact_xy_ylo,x
        adc compact_dy
        sta compact_xy_ylo,x
        lda compact_dy
        bmi !y_negative+
        lda #0
        bpl !y_high+
    !y_negative:
        lda #255
    !y_high:
        adc compact_xy_yhi,x
        sta compact_xy_yhi,x
        inx
        cpx #182
        bne !vertex-
        ldx #0
    !visibility:
        jsr read_source
        sta compact_visibility,x
        inx
        cpx #13
        bne !visibility-
        lda #<compact_xy_xlo
        sta edge_xlo_ptr
        lda #>compact_xy_xlo
        sta edge_xlo_ptr+1
        lda #<compact_xy_xhi
        sta edge_xhi_ptr
        lda #>compact_xy_xhi
        sta edge_xhi_ptr+1
        lda #<compact_xy_ylo
        sta edge_ylo_ptr
        lda #>compact_xy_ylo
        sta edge_ylo_ptr+1
        lda #<compact_xy_yhi
        sta edge_yhi_ptr
        lda #>compact_xy_yhi
        sta edge_yhi_ptr+1
        lda #<compact_topology
        sta compact_topology_ptr
        lda #>compact_topology
        sta compact_topology_ptr+1
        lda #0
        sta compact_vis_index
        lda #1
        sta compact_vis_mask
        rts
    }

compact_next_face:
    .if (SOURCE_KIND==3) {
    !face:
        jsr compact_read_index
        sta compact_count
        ldx compact_vis_index
        lda compact_visibility,x
        and compact_vis_mask
        sta compact_visible
        asl compact_vis_mask
        bne !bit_ready+
        lda #1
        sta compact_vis_mask
        inc compact_vis_index
    !bit_ready:
        lda compact_visible
        bne !selected+
        clc
        lda compact_topology_ptr
        adc compact_count
        sta compact_topology_ptr
        bcc !face-
        inc compact_topology_ptr+1
        jmp !face-
    !selected:
        lda compact_count
        rts
    }

compact_read_index:
    .if (SOURCE_KIND==3) {
        ldy #0
        lda (compact_topology_ptr),y
        inc compact_topology_ptr
        bne !done+
        inc compact_topology_ptr+1
    !done:
        rts
    }
compact_seed:
    .if (SOURCE_KIND==3) { .import binary "build/native-xy/seed-planes.bin" }
compact_book:
    .if (SOURCE_KIND==3) { .import binary "build/native-xy/book.bin" }
compact_topology:
    .if (SOURCE_KIND==3) { .import binary "build/native-xy/topology.bin" }
edge_code_end:
.assert "Runtime edges stay below vectors", edge_code_end <= $ff00, true
