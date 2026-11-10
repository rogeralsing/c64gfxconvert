// Strategy B: canonical unions of sample intervals retain exact character rows.
// All geometry, DDA and descriptor work executes in render_polygons each frame.
.const DELTA_INTERVAL_CAPACITY = 36
.const DELTA_LINE_BYTES = DELTA_INTERVAL_CAPACITY * 2
.label delta_current_counts = $fb60
.label delta_history_counts = $fbb0
.label delta_dirty_rows = $fc00
.label delta_current_ptr = $40
.label delta_history_ptr = $42
.label delta_line = $44
.label delta_count = $45
.label delta_bytes = $46
.label delta_sort_i = $47
.label delta_sort_j = $48
.label delta_key_left = $49
.label delta_key_right = $4a
.label delta_temp_left = $4b
.label delta_running_left = $4c
.label delta_running_right = $4d
.label delta_read_offset = $4e
.label delta_write_offset = $4f
.label delta_pair = $50
.label delta_row = $51
.label delta_part = $52
.label delta_left = $53
.label delta_right = $54

* = $1600 "Dirty-row cache helpers and descriptor tables"
delta_init:
    // Invalid counts force every row to rebuild, independent of power-on RAM.
    lda #255
    ldx #74
!history:
    sta delta_history_counts,x
    dex
    bpl !history-
    lda #0
    ldx #23
!unused:
    sta coverage+1000,x
    dex
    bpl !unused-
    rts

delta_begin_frame:
    lda #0
    ldx #74
!counts:
    sta delta_current_counts,x
    dex
    bpl !counts-
    ldx #24
!dirty:
    sta delta_dirty_rows,x
    dex
    bpl !dirty-
    rts

delta_collect_face:
    lda raster_first
    sta delta_line
!sample:
    ldx delta_line
    lda span_left,x
    cmp span_right,x
    bcs !next+
    ldy raster_mask_bases,x
    cpy #8
    beq !middle+
    tay
    lda delta_rank3,y
    sta delta_left
    ldy span_right,x
    lda delta_rank3,y
    jmp !ranked+
!middle:
    tay
    lda delta_rank2,y
    sta delta_left
    ldy span_right,x
    lda delta_rank2,y
!ranked:
    sta delta_right
    cmp delta_left
    bcc !next+
    beq !next+
    lda delta_current_lo,x
    sta delta_current_ptr
    lda delta_current_hi,x
    sta delta_current_ptr+1
    lda delta_current_counts,x
    cmp #DELTA_INTERVAL_CAPACITY
    bcc !capacity+
    brk                             // At most 36 white checker faces exist.
!capacity:
    asl
    tay
    lda delta_left
    sta (delta_current_ptr),y
    iny
    lda delta_right
    sta (delta_current_ptr),y
    inc delta_current_counts,x
!next:
    inc delta_line
    lda delta_line
    cmp raster_sample_end
    bcc !sample-
    rts

delta_finish_frame:
    lda #0
    sta delta_line
!line:
    ldx delta_line
    lda delta_current_lo,x
    sta delta_current_ptr
    lda delta_current_hi,x
    sta delta_current_ptr+1
    lda delta_current_counts,x
    sta delta_count
    asl
    sta delta_bytes
    cmp #4
    bcc !canonical+
    jsr delta_sort_merge
!canonical:
    jsr delta_compare_line
    inc delta_line
    lda delta_line
    cmp #75
    bcc !line-
    jmp delta_rebuild_rows

delta_sort_merge:
    lda #2
    sta delta_sort_i
!sort:
    ldy delta_sort_i
    lda (delta_current_ptr),y
    sta delta_key_left
    iny
    lda (delta_current_ptr),y
    sta delta_key_right
    lda delta_sort_i
    sta delta_sort_j
!find:
    lda delta_sort_j
    beq !insert+
    sec
    sbc #2
    tay
    lda delta_key_left
    cmp (delta_current_ptr),y
    bcs !insert+
    lda (delta_current_ptr),y
    sta delta_temp_left
    iny
    lda (delta_current_ptr),y
    iny
    iny
    sta (delta_current_ptr),y
    dey
    lda delta_temp_left
    sta (delta_current_ptr),y
    dec delta_sort_j
    dec delta_sort_j
    jmp !find-
!insert:
    ldy delta_sort_j
    lda delta_key_left
    sta (delta_current_ptr),y
    iny
    lda delta_key_right
    sta (delta_current_ptr),y
    inc delta_sort_i
    inc delta_sort_i
    lda delta_sort_i
    cmp delta_bytes
    bcc !sort-

    ldy #0
    lda (delta_current_ptr),y
    sta delta_running_left
    iny
    lda (delta_current_ptr),y
    sta delta_running_right
    lda #0
    sta delta_write_offset
    lda #2
    sta delta_read_offset
!merge:
    ldy delta_read_offset
    lda (delta_current_ptr),y
    cmp delta_running_right
    bcc !overlap+
    beq !overlap+
    sta delta_key_left
    iny
    lda (delta_current_ptr),y
    sta delta_key_right
    jsr delta_write_running
    lda delta_key_left
    sta delta_running_left
    lda delta_key_right
    sta delta_running_right
    jmp !next+
!overlap:
    iny
    lda (delta_current_ptr),y
    cmp delta_running_right
    bcc !next+
    sta delta_running_right
!next:
    inc delta_read_offset
    inc delta_read_offset
    lda delta_read_offset
    cmp delta_bytes
    bcc !merge-
    jsr delta_write_running
    lda delta_write_offset
    sta delta_bytes
    lsr
    sta delta_count
    ldx delta_line
    sta delta_current_counts,x
    rts

delta_write_running:
    ldy delta_write_offset
    lda delta_running_left
    sta (delta_current_ptr),y
    iny
    lda delta_running_right
    sta (delta_current_ptr),y
    inc delta_write_offset
    inc delta_write_offset
    rts

delta_compare_line:
    ldx delta_line
    lda delta_history_lo,x
    sta delta_history_ptr
    lda delta_history_hi,x
    sta delta_history_ptr+1
    lda delta_count
    cmp delta_history_counts,x
    bne !different+
    lda delta_bytes
    beq !same+
    ldy #0
!compare:
    lda (delta_current_ptr),y
    cmp (delta_history_ptr),y
    bne !different+
    iny
    cpy delta_bytes
    bcc !compare-
!same:
    rts
!different:
    lda delta_count
    sta delta_history_counts,x
    ldy delta_row_index,x
    lda #1
    sta delta_dirty_rows,y
    lda delta_bytes
    beq !same-
    ldy #0
!copy:
    lda (delta_current_ptr),y
    sta (delta_history_ptr),y
    iny
    cpy delta_bytes
    bcc !copy-
    rts

delta_rebuild_rows:
    lda #0
    sta delta_row
    sta delta_line
!row:
    ldx delta_row
    lda delta_dirty_rows,x
    bne !dirty+
    lda delta_line
    clc
    adc #3
    sta delta_line
    jmp !next_row+
!dirty:
    ldx delta_line
    lda sample_row_lo,x
    sta raster_cover_ptr
    lda sample_row_hi,x
    clc
    adc #>coverage
    sta raster_cover_ptr+1
    lda #0
    ldy #0
    .for (var column = 0; column < 40; column++) {
        sta (raster_cover_ptr),y
        .if (column < 39) { iny }
    }
    lda #3
    sta delta_part
!part:
    jsr delta_replay_line
    inc delta_line
    dec delta_part
    bne !part-
!next_row:
    inc delta_row
    lda delta_row
    cmp #25
    bcs !done+
    jmp !row-
!done:
    rts

delta_replay_line:
    ldx delta_line
    lda delta_current_counts,x
    asl
    sta delta_bytes
    bne !not_empty+
    rts
!not_empty:
    lda delta_current_lo,x
    sta delta_current_ptr
    lda delta_current_hi,x
    sta delta_current_ptr+1
    lda #0
    sta delta_pair
!pair:
    ldy delta_pair
    lda (delta_current_ptr),y
    sta delta_left
    iny
    lda (delta_current_ptr),y
    sta delta_right
    ldx delta_line
    lda raster_mask_bases,x
    cmp #8
    beq !middle+
    ldy delta_left
    lda delta_from3,y
    sta span_left,x
    ldy delta_right
    lda delta_from3,y
    jmp !have_right+
!middle:
    ldy delta_left
    lda delta_from2,y
    sta span_left,x
    ldy delta_right
    lda delta_from2,y
!have_right:
    sta span_right,x
    stx raster_sample
    inx
    stx raster_sample_end
    jsr raster_fill_span
    inc delta_pair
    inc delta_pair
    lda delta_pair
    cmp delta_bytes
    bcc !pair-
    rts

delta_current_lo:
    .for (var line = 0; line < 75; line++) {
        .byte <(line < 56 ? $c000 + line*72 : $f600 + (line-56)*72)
    }
delta_current_hi:
    .for (var line = 0; line < 75; line++) {
        .byte >(line < 56 ? $c000 + line*72 : $f600 + (line-56)*72)
    }
delta_history_lo:
    .fill 75, <($e000+i*72)
delta_history_hi:
    .fill 75, >($e000+i*72)
delta_row_index:
    .fill 75, floor(i/3)
delta_rank3:
    .for (var x = 0; x < 256; x++) {
        .var column = floor(x/8)
        .var sub = x-column*8
        .byte column*3 + (sub>1 ? 1 : 0) + (sub>4 ? 1 : 0) + (sub>6 ? 1 : 0)
    }
delta_rank2:
    .for (var x = 0; x < 256; x++) {
        .var column = floor(x/8)
        .var sub = x-column*8
        .byte column*2 + (sub>1 ? 1 : 0) + (sub>6 ? 1 : 0)
    }
delta_from3:
    .for (var index = 0; index < 97; index++) {
        .var column = floor(index/3)
        .var part = index-column*3
        .byte min(255,column*8+(part==0 ? 1 : part==1 ? 4 : 6))
    }
delta_from2:
    .for (var index = 0; index < 65; index++) {
        .byte min(255,floor(index/2)*8+((index&1)==0 ? 1 : 6))
    }
delta_extra_end:
.assert "Dirty-row helpers must stay below the fixed font", delta_extra_end <= $2000, true
.assert "Current descriptors stay below I/O", $c000+56*72 <= $d000, true
.assert "History descriptors do not overlap current tail", $e000+75*72 <= $f600, true
.assert "Current tail does not overlap count arrays", $f600+19*72 <= delta_current_counts, true
.assert "Retained state avoids hardware vectors", delta_dirty_rows+25 <= $fffa, true
