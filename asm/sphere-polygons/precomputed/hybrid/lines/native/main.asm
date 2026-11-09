// Callable Q8 mathematical line primitive. No captured glyph sequences.
// Set the input labels below and JSR draw_line. Screen pointer is at $02/$03.
.label screen_ptr = $02
.label destination_ptr = $04
.label ge_ptr = $06
.label eq_ptr = $08
.label work_phase = $0a
.label work_base = $0b
.label work_major = $0c
.label work_remaining = $0d
.label work_relative = $0e
.label work_minor = $0f
.label work_column = $10
.label work_glyph = $11
.label work_xor = $12
.label work_eq = $13
.label work_axis_offset = $14
.label work_minor_limit = $15
.label work_slope_index = $16
.label work_temp = $17

* = $3000 "Callable Q8 line drawer"
draw_line:
    lda line_length
    bne !nonempty+
    rts
!nonempty:
    sta work_remaining
    lda line_phase
    sta work_phase
    lda line_v
    sta work_base
    lda line_u
    sta work_major
    lda line_n
    clc
    adc #8
    sta work_slope_index
    lda line_positive
    eor line_include
    sta work_eq
    lda line_positive
    sec
    sbc #1
    sta work_xor
    lda line_axis
    asl
    clc
    adc line_axis
    sta work_axis_offset
    lda #25
    ldx line_axis
    beq !minor_limit+
    lda #40
!minor_limit:
    sta work_minor_limit

    // Move from descriptor anchor to requested majorStart using exactly the
    // same signed phase recurrence as the drawing loop. No multiply needed.
!seek:
    lda work_major
    cmp line_major_start
    beq !major+
    bcs !backward+
    jsr advance_phase
    inc work_major
    jmp !seek-
!backward:
    lda work_phase
    sec
    sbc line_n
    jsr normalize_phase
    dec work_major
    jmp !seek-

!major:
    // index = (n+8)*48 + phase*6 + axis*3; Y selects relative -1,0,+1.
    lda work_phase
    asl
    sta work_temp
    asl
    clc
    adc work_temp
    adc work_axis_offset
    ldx work_slope_index
    clc
    adc slope_offset_lo,x
    sta ge_ptr
    sta eq_ptr
    lda slope_offset_hi,x
    adc #>ge_table
    sta ge_ptr+1
    clc
    adc #4
    sta eq_ptr+1
    lda #0
    sta work_relative
!candidate:
    ldy work_relative
    tya
    clc
    adc work_base
    sec
    sbc #1
    cmp work_minor_limit
    bcs !next_candidate+
    sta work_minor
    lda (ge_ptr),y
    eor work_xor
    ldx work_eq
    beq !mask_ready+
    // Equality is a subset of GE: XOR implements removal or reinclusion.
    eor (eq_ptr),y
!mask_ready:
    cmp #0
    beq !next_candidate+
    cmp #255
    beq !next_candidate+
    tax
    lda glyph_lut,x
    sta work_glyph
    lda line_axis
    beq !horizontal+
    ldx work_major
    lda work_minor
    jmp !coordinate+
!horizontal:
    ldx work_minor
    lda work_major
!coordinate:
    sta work_column
    clc
    lda row_offset_lo,x
    adc screen_ptr
    sta destination_ptr
    lda row_offset_hi,x
    adc screen_ptr+1
    sta destination_ptr+1
    clc
    lda destination_ptr
    adc work_column
    sta destination_ptr
    bcc !address_ready+
    inc destination_ptr+1
!address_ready:
    ldy #0
    lda work_glyph
    sta (destination_ptr),y
!next_candidate:
    inc work_relative
    lda work_relative
    cmp #3
    bne !candidate-
    dec work_remaining
    beq !done+
    jsr advance_phase
    inc work_major
    jmp !major-
!done:
    rts

advance_phase:
    lda work_phase
    clc
    adc line_n
normalize_phase:
    // With |n|<=8 and phase in0..7, at most one carry/borrow is possible.
    bmi !negative+
    cmp #8
    bcc !normalized+
    sec
    sbc #8
    inc work_base
    jmp !normalized+
!negative:
    clc
    adc #8
    dec work_base
!normalized:
    sta work_phase
    rts

// Inputs: all are bytes. n is signed; the remaining inputs are unsigned.
line_n:           .byte 3
line_axis:        .byte 0
line_phase:       .byte 2
line_u:           .byte 0
line_v:           .byte 5
line_positive:    .byte 1
line_include:     .byte 1
line_major_start: .byte 0
line_length:      .byte 40
line_code_end:

// Small mathematical address constants, separate from the mask/glyph tables.
slope_offset_lo: .fill 17, <(i*48)
slope_offset_hi: .fill 17, >(i*48)
row_offset_lo:   .fill 25, <(i*40)
row_offset_hi:   .fill 25, >(i*40)
address_tables_end:

* = $4000 "Q8 greater-or-equal masks"
ge_table: .import binary "../build/q8-ge.bin"
ge_end:
.assert "Q8 GE bytes", ge_end-ge_table, 816
* = $4400 "Q8 equality masks"
eq_table: .import binary "../build/q8-eq.bin"
eq_end:
.assert "Q8 EQ bytes", eq_end-eq_table, 816
* = $4800 "Coverage-to-font glyph lookup"
glyph_lut: .import binary "../build/glyph-lut.bin"
glyph_lut_end:
.assert "Glyph lookup bytes", glyph_lut_end-glyph_lut, 256
