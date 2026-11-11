// Four 8-bit fractional PCM cursors through the SID volume DAC.
// Four lookups retain sub-nibble precision; the selected quantizer runs once.
#if SAMPLE_OFFSETS
#define EXTENDED_READS
#else
#if VARIABLE_TICKS
#define EXTENDED_READS
#else
#if LOOP_TARGETS
#define EXTENDED_READS
#endif
#endif
#endif
.label SID=$d400
.label fraction=$20
.label current_loop_lo=$24
.label current_loop_hi=$28
.label mix=$2c
.label residual=$30
.label next_dac=$31
.label tick_samples=$32
.label next_tick_samples=$33
.label tick_error=$34
.label played_tick_count=$36
.label underrun_counter=$38
.label stream_ptr=$40
.label playlist_ptr=$42
.label hold_ticks=$44
.label field_flags=$45
.label voice_mask=$46
.label decode_request=$47
.label pending_ready=$48
.label pending_done=$49
.label shadow_id=$50
.label shadow_step=$54
.label shadow_volume=$58
.label shadow_start_lo=$5c
.label shadow_start_hi=$60
.label shadow_loop_lo=$64
.label shadow_loop_hi=$68
.label shadow_reset=$6c
#if SCORE_DICTIONARY
.label phrase_ptr=$70
.label phrase_remaining=$72
#endif
#if SAMPLE_OFFSETS
.label shadow_offset_lo=$74
.label shadow_offset_hi=$78
.label shadow_offset_fraction=$7c
#endif
#if LOOP_TARGETS
.label shadow_loop_id=$80
.label stopped=$3a
#endif

BasicUpstart2(start)

.macro ReadExtendedStreamByte() {
    ldx #0
    lda (stream_ptr,x)
    inc stream_ptr
    bne !read+
    inc stream_ptr+1
!read:
}

.macro Commit(i, source, volume, step) {
#if LOOP_TARGETS
    // A finished one-shot remains on the silent DAC value until a later
    // Paula loop-pointer update resumes it; preserve the fractional phase.
    lda stopped+i
    beq !running+
    lda shadow_reset+i
    bne !resume_trigger+
    lda shadow_loop_lo+i
    cmp #<silence_sample
    bne !new_loop+
    lda shadow_loop_hi+i
    cmp #>silence_sample
    bne !new_loop+
    lda #0
    jmp !step_ready+
!new_loop:
    lda shadow_loop_lo+i
    sta source+1
    lda shadow_loop_hi+i
    sta source+2
!resume_trigger:
    lda #0
    sta stopped+i
!running:
#endif
    lda shadow_step+i
#if LOOP_TARGETS
!step_ready:
#endif
    sta step+1
    lda shadow_volume+i
    sta volume+1
#if LOOP_TARGETS
    lda shadow_loop_lo+i
    sta current_loop_lo+i
    lda shadow_loop_hi+i
    sta current_loop_hi+i
#endif
    lda shadow_reset+i
    beq !kept+
    lda shadow_start_lo+i
    sta source+1
    lda shadow_start_hi+i
    sta source+2
#if LOOP_TARGETS
#else
    lda shadow_loop_lo+i
    sta current_loop_lo+i
    lda shadow_loop_hi+i
    sta current_loop_hi+i
#endif
#if SAMPLE_OFFSETS
    lda shadow_offset_fraction+i
#else
    lda #0
#endif
    sta fraction+i
!kept:
}

start:
    sei
    cld
    ldx #$ff
    txs
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $dc0e
    sta $dd0e
    sta $d011
    sta $d015
    sta $d01a
    lda #$ff
    sta $d019
    lda #$35
    sta $01
    lda #0
    ldx #$4f
!clear:
    sta $20,x
    dex
    bpl !clear-
#if SCORE_DICTIONARY
    sta phrase_remaining
#endif
    ldx #24
!sid_clear:
    sta SID,x
    dex
    bpl !sid_clear-
    lda #8
    sta next_dac
    sta SID+24
    lda #<irq
    sta $fffe
    lda #>irq
    sta $ffff
    lda #<song_playlist
    sta playlist_ptr
    lda #>song_playlist
    sta playlist_ptr+1
    jsr next_block
    jsr decode_pending
    :Commit(0,read0,vol0,step0)
    :Commit(1,read1,vol1,step1)
    :Commit(2,read2,vol2,step2)
    :Commit(3,read3,vol3,step3)
    lda #1
    sta played_tick_count
#if VARIABLE_TICKS
    lda next_tick_samples
    sta tick_samples
    jsr decode_pending
#else
    lda #200
    sta tick_error
    lda #0
    sta tick_error+1
    jsr prepare_tick_length
    lda next_tick_samples
    sta tick_samples
    jsr prepare_tick_length
    jsr decode_pending
#endif
    lda #$ff
    sta $dc04
    lda #0
    sta $dc05
    lda #$81
    sta $dc0d
song_started:
    lda #$11
    sta $dc0e
    cli
!wait:
    lda decode_request
    beq !wait-
    dec decode_request
#if VARIABLE_TICKS
#else
    jsr prepare_tick_length
#endif
    jsr decode_pending
    jmp !wait-

done:
    sei
    lda #0
    sta $dc0e
    sta SID+24
    lda #$7f
    sta $dc0d
    lda $dc0d
!halt:
    jmp !halt-

#if VARIABLE_TICKS
#else
prepare_tick_length:
    clc
    lda tick_error
    adc #$85
    sta tick_error
    lda tick_error+1
    adc #1
    sta tick_error+1
    cmp #1
    bcc !short+
    bne !long+
    lda tick_error
    cmp #$90
    bcc !short+
!long:
    sec
    lda tick_error
    sbc #$90
    sta tick_error
    lda tick_error+1
    sbc #1
    sta tick_error+1
    lda #77
    sta next_tick_samples
    rts
!short:
    lda #76
    sta next_tick_samples
    rts
#endif

get_byte:
#if SCORE_DICTIONARY
    // Dictionary phrases are raw, non-recursive bytes. Only the foreground
    // decoder handles them; the sample IRQ and its timing are unchanged.
    lda phrase_remaining
    beq !stream+
    dec phrase_remaining
#if EXTENDED_READS
    // The IRQ never touches X. This complete indirect read needs no IRQ mask.
    ldx #0
    lda (phrase_ptr,x)
#else
    php
    sei
    ldy #0
    lda (phrase_ptr),y
    plp
#endif
    inc phrase_ptr
    bne !ready+
    inc phrase_ptr+1
!ready:
    ora #0
    rts
!stream:
#if EXTENDED_READS
    // Keep literal/control reads inline in the extended foreground decoder.
    // CMP below restores flags after pointer increments, so no extra ORA is needed.
    :ReadExtendedStreamByte()
#else
    jsr get_stream_byte
#endif
#if SCORE_DICTIONARY_8
    cmp #$c0
    bcc !literal+
    beq !escaped+
    sec
    sbc #$c0
#else
    cmp #$fe
    bne !literal+
    jsr get_stream_byte
    beq !escaped+
#endif
    tax
    lda phrase_start_lo,x
    sta phrase_ptr
    lda phrase_start_hi,x
    sta phrase_ptr+1
    lda phrase_lengths,x
    sta phrase_remaining
    jmp get_byte
!escaped:
#if SCORE_DICTIONARY_8
    jsr get_stream_byte
#else
    lda #$fe
#endif
!literal:
    ora #0
    rts

get_stream_byte:
#endif
    // IRQ owns Y. Protect only the indexed read; it never touches X.
#if EXTENDED_READS
    // The IRQ never touches X. This complete indirect read needs no IRQ mask.
    :ReadExtendedStreamByte()
#else
    php
    sei
    ldy #0
    lda (stream_ptr),y
    plp
    inc stream_ptr
    bne !ready+
    inc stream_ptr+1
!ready:
#endif
    ora #0
    rts

next_block:
    php
    sei
    ldy #0
    lda (playlist_ptr),y
    sta stream_ptr
    iny
    lda (playlist_ptr),y
    sta stream_ptr+1
    plp
    ora stream_ptr
    bne !present+
    lda #1
    sta pending_done
    rts
!present:
    clc
    lda playlist_ptr
    adc #2
    sta playlist_ptr
    bcc !ready+
    inc playlist_ptr+1
!ready:
    rts

.macro DecodeVoice(i) {
    jsr get_byte
    sta field_flags
    and #1
    beq !id_done+
    jsr get_byte
    sta shadow_id+i
!id_done:
    lda field_flags
    and #2
    beq !step_done+
    jsr get_byte
    sta shadow_step+i
!step_done:
    lda field_flags
    and #4
    beq !volume_done+
    jsr get_byte
    asl
    asl
    asl
    asl
    sta shadow_volume+i
!volume_done:
#if SAMPLE_OFFSETS
    lda #0
    sta shadow_offset_lo+i
    sta shadow_offset_hi+i
    sta shadow_offset_fraction+i
    lda field_flags
    and #16
    beq !offset_done+
    jsr get_byte
    sta shadow_offset_lo+i
    jsr get_byte
    sta shadow_offset_hi+i
    jsr get_byte
    sta shadow_offset_fraction+i
!offset_done:
#endif
#if LOOP_TARGETS
    lda field_flags
    and #32
    beq !loop_id_done+
    jsr get_byte
    sta shadow_loop_id+i
    // Cache the descriptor only when its ID changes. Volume/step updates
    // and retriggers of the same instrument retain these prepared pointers.
    tax
    lda bank_loop_lo,x
    sta shadow_loop_lo+i
    lda bank_loop_hi,x
    sta shadow_loop_hi+i
!loop_id_done:
#endif
    lda field_flags
    and #8
    bne !reset+
    lda shadow_id+i
    bne !done+
!reset:
    lda #1
    sta shadow_reset+i
    ldx shadow_id+i
    bne !active+
    lda #0
    sta shadow_step+i
!active:
    lda bank_start_lo,x
#if SAMPLE_OFFSETS
    clc
    adc shadow_offset_lo+i
#endif
    sta shadow_start_lo+i
    lda bank_start_hi,x
#if SAMPLE_OFFSETS
    adc shadow_offset_hi+i
#endif
    sta shadow_start_hi+i
#if LOOP_TARGETS
!done:
#else
    lda bank_loop_lo,x
    sta shadow_loop_lo+i
    lda bank_loop_hi,x
    sta shadow_loop_hi+i
!done:
#endif
}

decode_pending:
    lda #0
    sta pending_ready
    sta pending_done
    sta shadow_reset
    sta shadow_reset+1
    sta shadow_reset+2
    sta shadow_reset+3
    lda hold_ticks
    beq !command+
    dec hold_ticks
    jmp !ready+
!command:
    jsr get_byte
    bne !not_end+
    jsr next_block
    lda pending_done
    beq !command-
    jmp !ready+
!not_end:
    bmi !packet+
    sec
    sbc #1
    sta hold_ticks
    jmp !ready+
!packet:
    sta voice_mask
#if VARIABLE_TICKS
    and #16
    beq !duration_done+
    jsr get_byte
    sta next_tick_samples
!duration_done:
    lda voice_mask
#endif
    and #1
#if SAMPLE_OFFSETS
    bne !decode0+
    jmp !v0+
!decode0:
#else
    beq !v0+
#endif
    :DecodeVoice(0)
!v0:
    lda voice_mask
    and #2
#if SAMPLE_OFFSETS
    bne !decode1+
    jmp !v1+
!decode1:
#else
    beq !v1+
#endif
    :DecodeVoice(1)
!v1:
    lda voice_mask
    and #4
#if SAMPLE_OFFSETS
    bne !decode2+
    jmp !v2+
!decode2:
#else
    beq !v2+
#endif
    :DecodeVoice(2)
!v2:
    lda voice_mask
    and #8
#if SAMPLE_OFFSETS
    bne !decode3+
    jmp !v3+
!decode3:
#else
    beq !v3+
#endif
    :DecodeVoice(3)
!v3:
!ready:
    lda #1
    sta pending_ready
    rts

irq:
    pha
    lda $dc0d
    lda next_dac
    sta SID+24
    // Deterministic one-voice commit, staged before the end of each tick.
    lda tick_samples
#if LOOP_TARGETS
    // Extended commits are separated by recovery IRQs. Four adjacent heavy
    // commits can otherwise coalesce CIA timer events even with ready data.
    cmp #9
    bcs !ordinary+
    lsr
    bcc !stagger+
!ordinary:
    jmp mixer_begin
#else
    cmp #5
    bcc !stagger+
    jmp mixer_begin
#endif
!stagger:
    lda pending_ready
    bne !ready+
    inc underrun_counter
    bne !late+
    inc underrun_counter+1
!late:
    jmp mixer_begin
!ready:
    lda pending_done
    beq !commit+
    jmp mixer_begin
!commit:
    lda tick_samples
#if LOOP_TARGETS
    lsr
#endif
    cmp #4
#if LOOP_TARGETS
    beq !commit0+
    jmp !check1+
!commit0:
#else
    bne !check1+
#endif
    :Commit(0,read0,vol0,step0)
    jmp mixer_begin
!check1:
    cmp #3
#if LOOP_TARGETS
    beq !commit1+
    jmp !check2+
!commit1:
#else
    bne !check2+
#endif
    :Commit(1,read1,vol1,step1)
    jmp mixer_begin
!check2:
    cmp #2
#if LOOP_TARGETS
    beq !commit2+
    jmp !check3+
!commit2:
#else
    bne !check3+
#endif
    :Commit(2,read2,vol2,step2)
    jmp mixer_begin
!check3:
    :Commit(3,read3,vol3,step3)
mixer_begin:

read0:
    lda silence_sample
    bpl sample0
#if LOOP_TARGETS
    // End markers choose the current next-loop descriptor. A source bank's
    // non-loop marker must not stop a newly selected real loop.
    lda current_loop_lo+0
    cmp #<silence_sample
    bne loop0
    lda current_loop_hi+0
    cmp #>silence_sample
    bne loop0
    lda #1
    sta stopped+0
#else
    cmp #$81
    bne loop0
#endif
    lda #0
    sta step0+1
loop0:
    lda current_loop_lo+0
    sta read0+1
    lda current_loop_hi+0
    sta read0+2
    jmp read0
sample0:
vol0:
    ora #0
    tay
    lda volume_table,y
    sta mix+0
    lda fraction+0
    clc
step0:
    adc #0
    sta fraction+0
    bcc advance_done0
    inc read0+1
    bne advance_done0
    inc read0+2
advance_done0:

read1:
    lda silence_sample
    bpl sample1
#if LOOP_TARGETS
    // End markers choose the current next-loop descriptor. A source bank's
    // non-loop marker must not stop a newly selected real loop.
    lda current_loop_lo+1
    cmp #<silence_sample
    bne loop1
    lda current_loop_hi+1
    cmp #>silence_sample
    bne loop1
    lda #1
    sta stopped+1
#else
    cmp #$81
    bne loop1
#endif
    lda #0
    sta step1+1
loop1:
    lda current_loop_lo+1
    sta read1+1
    lda current_loop_hi+1
    sta read1+2
    jmp read1
sample1:
vol1:
    ora #0
    tay
    lda volume_table,y
    sta mix+1
    lda fraction+1
    clc
step1:
    adc #0
    sta fraction+1
    bcc advance_done1
    inc read1+1
    bne advance_done1
    inc read1+2
advance_done1:

read2:
    lda silence_sample
    bpl sample2
#if LOOP_TARGETS
    // End markers choose the current next-loop descriptor. A source bank's
    // non-loop marker must not stop a newly selected real loop.
    lda current_loop_lo+2
    cmp #<silence_sample
    bne loop2
    lda current_loop_hi+2
    cmp #>silence_sample
    bne loop2
    lda #1
    sta stopped+2
#else
    cmp #$81
    bne loop2
#endif
    lda #0
    sta step2+1
loop2:
    lda current_loop_lo+2
    sta read2+1
    lda current_loop_hi+2
    sta read2+2
    jmp read2
sample2:
vol2:
    ora #0
    tay
    lda volume_table,y
    sta mix+2
    lda fraction+2
    clc
step2:
    adc #0
    sta fraction+2
    bcc advance_done2
    inc read2+1
    bne advance_done2
    inc read2+2
advance_done2:

read3:
    lda silence_sample
    bpl sample3
#if LOOP_TARGETS
    // End markers choose the current next-loop descriptor. A source bank's
    // non-loop marker must not stop a newly selected real loop.
    lda current_loop_lo+3
    cmp #<silence_sample
    bne loop3
    lda current_loop_hi+3
    cmp #>silence_sample
    bne loop3
    lda #1
    sta stopped+3
#else
    cmp #$81
    bne loop3
#endif
    lda #0
    sta step3+1
loop3:
    lda current_loop_lo+3
    sta read3+1
    lda current_loop_hi+3
    sta read3+2
    jmp read3
sample3:
vol3:
    ora #0
    tay
    lda volume_table,y
    sta mix+3
    lda fraction+3
    clc
step3:
    adc #0
    sta fraction+3
    bcc advance_done3
    inc read3+1
    bne advance_done3
    inc read3+2
advance_done3:

    clc
    lda mix
    adc mix+1
    adc mix+2
    adc mix+3
    .if (QUANTIZER_NEAREST == 1) {
        tay
        lda quantize_table,y
        sta next_dac
    } else {
    adc residual
    tay
    and #15
    sta residual
    tya
    lsr
    lsr
    lsr
    lsr
    sta next_dac
    }
    dec tick_samples
    bne !return+
    lda pending_done
    beq !next_tick+
    jmp done
!next_tick:
    lda next_tick_samples
    sta tick_samples
    inc played_tick_count
    bne !counted+
    inc played_tick_count+1
!counted:
    lda #0
    sta pending_ready
    inc decode_request
!return:
    pla
    rti
player_end:
silence_sample: .byte 8,$81

