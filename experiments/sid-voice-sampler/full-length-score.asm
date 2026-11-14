// Native streaming decoder for exact24-byte physical score rows.
// A/X/Y are caller-clobbered. NMI must preserve A and leave X/Y untouched.
.label score_wait = $40
.label score_groups = $41
.label score_fields = $42
.label score_lz_flags = $43
.label score_lz_bits = $44
.label score_match_remaining = $45
.label score_word_lo = $46
.label score_word_hi = $47
.label score_distance_hi = $48
.label score_frames_decoded = $49
.label score_exhausted = $4b
.label score_pcm_id = $4c
.label score_previous_pcm_id = $4d
.label score_read_ptr = $4e
.label score_write_ptr = $50

// Inline only the common continuation of an existing LZ match. Token parsing
// remains shared; no compressed-byte format or history semantics change.
.macro ScoreByte() {
    lda score_match_remaining
    beq !token+
    dec score_match_remaining
    lda (score_read_ptr),y
    inc score_read_ptr
    bne !read_ready+
    pha
    inc score_read_ptr+1
    lda score_read_ptr+1
    and #$0f
    ora #$e0
    sta score_read_ptr+1
    pla
!read_ready:
    sta (score_write_ptr),y
    inc score_write_ptr
    bne !ready+
    pha
    inc score_write_ptr+1
    lda score_write_ptr+1
    and #$0f
    ora #$e0
    sta score_write_ptr+1
    pla
    jmp !ready+
!token:
    jsr score_token
!ready:
    ora #0
}

score_init:
    lda #0
    ldx #$11
!clear_state:
    sta $40,x
    dex
    bpl !clear_state-
    ldx #23
!clear_row:
    sta tick_record,x
    dex
    bpl !clear_row-
    lda #$ff
    sta score_previous_pcm_id
    lda #<(score_data+SCORE_HEADER_BYTES)
    sta score_fetch_read+1
    lda #>(score_data+SCORE_HEADER_BYTES)
    sta score_fetch_read+2
    lda #0
    sta score_write_ptr
    lda #$e0
    sta score_write_ptr+1
    rts

decode_next_tick:
score_next_tick:
    lda score_exhausted
    beq !decode+
    sec
    rts
!decode:
    // The NMI leaves Y unchanged. Keeping it zero avoids indexed-load setup
    // for every decoded byte, including the inlined match continuations.
    ldy #0
    lda #0
    sta tick_record+15
    sta tick_record+22
    lda tick_record+23
    and #$fc
    sta tick_record+23
    lda score_wait
    beq !packet+
    dec score_wait
    jmp score_row_ready
!packet:
    :ScoreByte()
    bne !changes+
    :ScoreByte()
    sec
    sbc #1
    sta score_wait
    jmp score_row_ready
!changes:
    sta score_groups
    .for (var group=0; group<3; group++) {
        lda score_groups
        and #(1<<group)
        bne !present_group+
        jmp !next_group+
!present_group:
        :ScoreByte()
        sta score_fields
        .for (var bit=0; bit<8; bit++) {
            lsr score_fields
            bcc !kept+
            .if (SCORE_PCM_DESCRIPTORS == 1 && group*8+bit >= 17 && group*8+bit < 22) {
                jsr score_get_byte
            } else {
                :ScoreByte()
            }
            .if (SCORE_PCM_DESCRIPTORS == 1 && group*8+bit == 16) {
                sta score_pcm_id
            } else {
                sta tick_record+group*8+bit
            }
!kept:
        }
!next_group:
    }
score_row_ready:
    .if (SCORE_PCM_DESCRIPTORS == 1) {
        ldx score_pcm_id
        cpx score_previous_pcm_id
        beq !pcm_kept+
        stx score_previous_pcm_id
        lda score_pcm_table_16,x
        sta tick_record+16
        lda score_pcm_table_17,x
        sta tick_record+17
        lda score_pcm_table_18,x
        sta tick_record+18
        lda score_pcm_table_19,x
        sta tick_record+19
        lda score_pcm_table_20,x
        sta tick_record+20
        lda score_pcm_table_21,x
        sta tick_record+21
!pcm_kept:
    }
    inc score_frames_decoded
    bne !counted+
    inc score_frames_decoded+1
!counted:
    lda score_frames_decoded
    cmp #<FRAME_COUNT
    bne !ready+
    lda score_frames_decoded+1
    cmp #>FRAME_COUNT
    bne !ready+
    lda #1
    sta score_exhausted
!ready:
    clc
    rts

score_get_byte:
    lda score_match_remaining
    beq score_token
score_history_read:
    lda (score_read_ptr),y
    inc score_read_ptr
    bne !read_ready+
    pha
    inc score_read_ptr+1
    lda score_read_ptr+1
    and #$0f
    ora #$e0
    sta score_read_ptr+1
    pla
!read_ready:
    dec score_match_remaining
    jmp score_emit
score_token:
    lda score_lz_bits
    bne !flags_ready+
    jsr score_fetch
    sta score_lz_flags
    lda #8
    sta score_lz_bits
!flags_ready:
    dec score_lz_bits
    lsr score_lz_flags
    bcs score_literal
    jsr score_fetch
    sta score_word_lo
    jsr score_fetch
    sta score_word_hi
    lsr
    lsr
    lsr
    lsr
    .if (SCORE_LONG_MATCHES == 1) {
        cmp #15
        bne !short_match+
        jsr score_fetch
        clc
        adc #18
        jmp !length_ready+
!short_match:
    }
    clc
    adc #3
!length_ready:
    sta score_match_remaining
    lda score_word_hi
    and #$0f
    sta score_distance_hi
    lda score_write_ptr
    clc
    sbc score_word_lo
    sta score_read_ptr
    lda score_write_ptr+1
    sbc score_distance_hi
    and #$0f
    ora #$e0
    sta score_read_ptr+1
    jmp score_get_byte
score_literal:
    jsr score_fetch
score_emit:
score_history_write:
    sta (score_write_ptr),y
    inc score_write_ptr
    bne !write_ready+
    pha
    inc score_write_ptr+1
    lda score_write_ptr+1
    and #$0f
    ora #$e0
    sta score_write_ptr+1
    pla
!write_ready:
    ora #0
    rts
score_fetch:
score_fetch_read:
    lda $ffff
    inc score_fetch_read+1
    bne !ready+
    inc score_fetch_read+2
!ready:
    rts
decoder_end:
.assert "Full score decoder below SID programs", decoder_end <= $f800, true
