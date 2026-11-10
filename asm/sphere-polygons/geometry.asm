// Q3 character-space projection. One unit is one eighth of a character.
// Static-coordinate product pages are indexed by signed Q6 matrix bytes.
.label matrix_xx = $80
.label matrix_xz = $81
.label matrix_yx = $82
.label matrix_yy = $83
.label matrix_yz = $84
.label matrix_zx = $85
.label matrix_zy = $86
.label matrix_zz = $87
.label vertices_base = $88
.label faces_base = $8a
.label geo_vertex_ptr = $8c
.label geo_product_ptr = $8e
.label geo_sum = $90
.label geo_vertex_index = $91
.label geo_x_page = $92
.label geo_y_page = $93
.label geo_z_page = $94
.label geo_sin_yaw = $95
.label geo_cos_yaw = $96
.label geo_sin_pitch = $97
.label geo_cos_pitch = $98
.label geo_mul_a = $99
.label geo_mul_b = $9a
.label geo_mul_temp = $9b
.label matrix_xy = $9c
.label geo_sin_roll = $9d
.label geo_cos_roll = $9e
.label geo_roll_temp = $9f

select_model:
    and #1
    beq !checker+
    lda #60
    sta vertex_count
    lda #32
    sta face_count
    lda #<football_vertices
    sta vertices_base
    lda #>football_vertices
    sta vertices_base+1
    lda #<football_faces
    sta faces_base
    lda #>football_faces
    sta faces_base+1
    rts
!checker:
    lda #62
    sta vertex_count
    lda #72
    sta face_count
    lda #<checker_vertices
    sta vertices_base
    lda #>checker_vertices
    sta vertices_base+1
    lda #<checker_faces
    sta faces_base
    lda #>checker_faces
    sta faces_base+1
    rts

prepare_matrix:
    ldx angle_yaw
    lda sin_table,x
    sta geo_sin_yaw
    sta matrix_xz
    txa
    clc
    adc #64
    tax
    lda sin_table,x
    sta geo_cos_yaw
    sta matrix_xx
    ldx angle_pitch
    lda sin_table,x
    sta geo_sin_pitch
    sta matrix_zy
    txa
    clc
    adc #64
    tax
    lda sin_table,x
    sta geo_cos_pitch
    sta matrix_yy

    lda geo_sin_pitch
    ldx geo_sin_yaw
    jsr geo_multiply_q6
    sta matrix_yx
    lda geo_sin_pitch
    ldx geo_cos_yaw
    jsr geo_multiply_q6
    eor #$ff
    clc
    adc #1
    sta matrix_yz
    lda geo_cos_pitch
    ldx geo_sin_yaw
    jsr geo_multiply_q6
    eor #$ff
    clc
    adc #1
    sta matrix_zx
    lda geo_cos_pitch
    ldx geo_cos_yaw
    jsr geo_multiply_q6
    sta matrix_zz
    lda #0
    sta matrix_xy
    lda angle_roll
    beq !no_roll+
    jsr geo_roll_matrix
!no_roll:
    rts

// Apply camera-Z roll to the already prepared X/Y rows. Keep the depth row.
geo_roll_matrix:
    lda matrix_xx
    sta geo_old_xx
    lda matrix_xz
    sta geo_old_xz
    lda matrix_yx
    sta geo_old_yx
    lda matrix_yy
    sta geo_old_yy
    lda matrix_yz
    sta geo_old_yz
    ldx angle_roll
    lda sin_table,x
    sta geo_sin_roll
    txa
    clc
    adc #64
    tax
    lda sin_table,x
    sta geo_cos_roll

    lda geo_cos_roll
    ldx geo_old_xx
    jsr geo_multiply_q6
    sta geo_roll_temp
    lda geo_sin_roll
    ldx geo_old_yx
    jsr geo_multiply_q6
    sta geo_sum
    lda geo_roll_temp
    sec
    sbc geo_sum
    sta matrix_xx

    lda geo_sin_roll
    ldx geo_old_yy
    jsr geo_multiply_q6
    eor #$ff
    clc
    adc #1
    sta matrix_xy

    lda geo_cos_roll
    ldx geo_old_xz
    jsr geo_multiply_q6
    sta geo_roll_temp
    lda geo_sin_roll
    ldx geo_old_yz
    jsr geo_multiply_q6
    sta geo_sum
    lda geo_roll_temp
    sec
    sbc geo_sum
    sta matrix_xz

    lda geo_sin_roll
    ldx geo_old_xx
    jsr geo_multiply_q6
    sta geo_roll_temp
    lda geo_cos_roll
    ldx geo_old_yx
    jsr geo_multiply_q6
    clc
    adc geo_roll_temp
    sta matrix_yx

    lda geo_cos_roll
    ldx geo_old_yy
    jsr geo_multiply_q6
    sta matrix_yy

    lda geo_sin_roll
    ldx geo_old_xz
    jsr geo_multiply_q6
    sta geo_roll_temp
    lda geo_cos_roll
    ldx geo_old_yz
    jsr geo_multiply_q6
    clc
    adc geo_roll_temp
    sta matrix_yz
    rts

// A*X in Q6. The quarter-square identity is exact for this table's rounding.
geo_multiply_q6:
    sta geo_mul_a
    stx geo_mul_b
    clc
    adc geo_mul_b
    tax
    lda geo_quarter_squares,x
    sta geo_mul_temp
    lda geo_mul_a
    sec
    sbc geo_mul_b
    tax
    lda geo_mul_temp
    sec
    sbc geo_quarter_squares,x
    rts

project_vertices:
    lda vertices_base
    sta geo_vertex_ptr
    lda vertices_base+1
    sta geo_vertex_ptr+1
    lda #0
    sta geo_product_ptr
    sta geo_vertex_index
!vertex:
    ldy #0
    lda (geo_vertex_ptr),y
    sta geo_x_page
    iny
    lda (geo_vertex_ptr),y
    sta geo_y_page
    iny
    lda (geo_vertex_ptr),y
    sta geo_z_page

    lda geo_x_page
    sta geo_product_ptr+1
    ldy matrix_xx
    lda (geo_product_ptr),y
    sta geo_sum
    lda geo_y_page
    sta geo_product_ptr+1
    ldy matrix_xy
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    sta geo_sum
    lda geo_z_page
    sta geo_product_ptr+1
    ldy matrix_xz
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    bmi !x_add_center+
    cmp #96
    bcc !x_add_center+
    lda #95
!x_add_center:
    clc
    adc #160
    ldy geo_vertex_index
    sta projected_x,y

    lda geo_x_page
    sta geo_product_ptr+1
    ldy matrix_yx
    lda (geo_product_ptr),y
    sta geo_sum
    lda geo_y_page
    sta geo_product_ptr+1
    ldy matrix_yy
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    sta geo_sum
    lda geo_z_page
    sta geo_product_ptr+1
    ldy matrix_yz
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    sta geo_sum
    bmi !negative_y+
    cmp #101
    bcc !y_subtract+
    lda #0
    jmp !y_ready+
!negative_y:
    cmp #$9d
    bcs !y_subtract+
    lda #199
    jmp !y_ready+
!y_subtract:
    lda #100
    sec
    sbc geo_sum
!y_ready:
    ldy geo_vertex_index
    sta projected_y,y

    clc
    lda geo_vertex_ptr
    adc #3
    sta geo_vertex_ptr
    bcc !pointer_ready+
    inc geo_vertex_ptr+1
!pointer_ready:
    inc geo_vertex_index
    lda geo_vertex_index
    cmp vertex_count
    bcs !vertices_done+
    jmp !vertex-
!vertices_done:
    // Keep unused array entries deterministic when switching between meshes.
    ldx vertex_count
    lda #0
!tail:
    cpx #64
    bcs !done+
    sta projected_x,x
    sta projected_y,x
    inx
    bne !tail-
!done:
    rts

face_front:
    // The raster's face_ptr remains untouched. Only geometry-owned ZP changes.
    lda #0
    sta geo_product_ptr
    ldy #2
    lda (face_ptr),y
    sta geo_product_ptr+1
    ldy matrix_zx
    lda (geo_product_ptr),y
    sta geo_sum
    ldy #3
    lda (face_ptr),y
    sta geo_product_ptr+1
    ldy matrix_zy
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    sta geo_sum
    ldy #4
    lda (face_ptr),y
    sta geo_product_ptr+1
    ldy matrix_zz
    lda (geo_product_ptr),y
    clc
    adc geo_sum
    sta normal_depth
    bmi !front+
    lda #0
    rts
!front:
    lda #1
    rts

vertex_count: .byte 0
face_count: .byte 0
normal_depth: .byte 0
geo_old_xx: .byte 0
geo_old_xz: .byte 0
geo_old_yx: .byte 0
geo_old_yy: .byte 0
geo_old_yz: .byte 0
geo_quarter_squares:
    .fill 256, floor(pow(i<128 ? i : i-256,2)/256)
