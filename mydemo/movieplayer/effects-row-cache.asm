// Source rows are immutable. Keep ten physical pointer tables across images,
// then map logical history ages to those tables. Protect every hit before
// choosing victims so the newest miss cannot evict an age still needed.
build_cache:
    lda next_mode
    cmp #1
    beq !retained+
    jmp build_cache_direct
!retained:
    lda #1
    sta cache_table_count
    lda next_mode
    cmp #1
    bne !two+
    lda #10
    sta cache_table_count
!two:
    lda next_mode
    cmp #2
    beq !set_two+
    cmp #7
    beq !set_two+
    cmp #8
    bne !requests+
!set_two:
    lda #2
    sta cache_table_count
!requests:
    ldx #9
    lda #0
!reset:
    sta row_pool_used,x
    dex
    bpl !reset-
    sta cache_slot
!request:
    lda next_object
    sta lookup_object
    lda cache_slot
    sta source_age
    lda next_mode
    cmp #7
    bcc !temporal+
    lda cache_slot
    sta lookup_object
    lda #0
    sta source_age
    jmp !age+
!temporal:
    cmp #2
    bne !age+
    lda cache_slot
    beq !age+
    lda #24
    sta source_age
!age:
    jsr age_to_frame
    ldx cache_slot
    sta cache_frame_ids,x
    lda lookup_object
    sta cache_object_ids,x
    lda #$ff
    sta row_logical_pool,x
    jsr find_cached_row_table
    bcc !next_request+
    jsr mark_cached_row_table
!next_request:
    inc cache_slot
    lda cache_slot
    cmp cache_table_count
    bne !request-

    lda #0
    sta cache_slot
!resolve:
    ldx cache_slot
    lda row_logical_pool,x
    cmp #$ff
    bne !map+
    // Earlier misses may already have created a duplicate request, most
    // commonly blank frame0 during the first history images of a scene.
    lda cache_slot
    beq !victim+
    jsr find_cached_row_table
    bcs !found+
!victim:
    ldx #0
!unused:
    lda row_pool_used,x
    beq !fill+
    inx
    cpx #10
    bne !unused-
    // At most ten distinct requests exist, so a missing request always
    // has an unprotected physical table available.
    brk
!fill:
    stx row_pool_fill_slot
    ldy cache_slot
    lda cache_frame_ids,y
    sta row_pool_frame_ids,x
    lda cache_object_ids,y
    sta row_pool_object_ids,x
    tax
    lda object_frame_base,x
    clc
    adc cache_frame_ids,y
    tax
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    ldx row_pool_fill_slot
    lda row_pool_pointer_low,x
    sta cache_write
    lda row_pool_pointer_high,x
    sta cache_write+1
    lda #25
    sta cache_rows_left
!row:
    ldy #0
    lda source_ptr
    sta (cache_write),y
    iny
    lda source_ptr+1
    sta (cache_write),y
    lda (source_ptr),y
    clc
    adc #2
    clc
    adc source_ptr
    sta source_ptr
    bcc !source+
    inc source_ptr+1
!source:
    lda cache_write
    clc
    adc #2
    sta cache_write
    bcc !cache+
    inc cache_write+1
!cache:
    dec cache_rows_left
    bne !row-
    ldx row_pool_fill_slot
!found:
    jsr mark_cached_row_table
    txa
!map:
    tax
    ldy cache_slot
    lda row_pool_pointer_low,x
    sta cache_pointer_low,y
    lda row_pool_pointer_high,x
    sta cache_pointer_high,y
    inc cache_slot
    lda cache_slot
    cmp cache_table_count
    beq !done+
    jmp !resolve-
!done:
    rts

// Return C=1 and X=physical slot for a matching (object, frame), else C=0.
find_cached_row_table:
    ldy cache_slot
    ldx #0
!slot:
    lda row_pool_frame_ids,x
    cmp cache_frame_ids,y
    bne !next+
    lda row_pool_object_ids,x
    cmp cache_object_ids,y
    beq !found+
!next:
    inx
    cpx #10
    bne !slot-
    clc
    rts
!found:
    sec
    rts

mark_cached_row_table:
    ldy cache_slot
    txa
    sta row_logical_pool,y
    lda #1
    sta row_pool_used,x
    rts

row_pool_fill_slot: .byte 0
row_pool_frame_ids: .fill 10,$ff
row_pool_object_ids: .fill 10,$ff
row_pool_used: .fill 10,0
row_logical_pool: .fill 10,0
row_pool_pointer_low: .fill 10,<(row_cache+i*50)
row_pool_pointer_high: .fill 10,>(row_cache+i*50)

// One- and two-table modes use a direct build. The short tag updates retain
// coherence with the history pool without searching it on every normal image.
build_cache_direct:
    lda #1
    sta cache_table_count
    lda next_mode
    cmp #2
    beq !two+
    cmp #7
    beq !two+
    cmp #8
    bne !begin+
!two:
    lda #2
    sta cache_table_count
!begin:
    lda #0
    sta cache_slot
!table:
    lda next_object
    sta lookup_object
    lda cache_slot
    sta source_age
    lda next_mode
    cmp #7
    bcc !temporal+
    lda cache_slot
    sta lookup_object
    lda #0
    sta source_age
    jmp !age+
!temporal:
    cmp #2
    bne !age+
    lda cache_slot
    beq !age+
    lda #24
    sta source_age
!age:
    jsr age_to_frame
    ldx cache_slot
    sta cache_frame_ids,x
    sta row_pool_frame_ids,x
    lda lookup_object
    sta cache_object_ids,x
    sta row_pool_object_ids,x
    lda row_pool_pointer_low,x
    sta cache_pointer_low,x
    sta cache_write
    lda row_pool_pointer_high,x
    sta cache_pointer_high,x
    sta cache_write+1
    ldy cache_slot
    lda cache_frame_ids,y
    ldx lookup_object
    clc
    adc object_frame_base,x
    tax
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    lda #25
    sta cache_rows_left
!row:
    ldy #0
    lda source_ptr
    sta (cache_write),y
    iny
    lda source_ptr+1
    sta (cache_write),y
    lda (source_ptr),y
    clc
    adc #2
    clc
    adc source_ptr
    sta source_ptr
    bcc !source+
    inc source_ptr+1
!source:
    lda cache_write
    clc
    adc #2
    sta cache_write
    bcc !cache+
    inc cache_write+1
!cache:
    dec cache_rows_left
    bne !row-
    inc cache_slot
    lda cache_slot
    cmp cache_table_count
    beq !done+
    jmp !table-
!done:
    rts
