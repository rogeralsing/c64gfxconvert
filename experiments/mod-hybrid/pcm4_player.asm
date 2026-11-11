// Four 8-bit fractional PCM cursors through the 6581 volume DAC.
// Four lookups retain sub-nibble precision; the selected quantizer runs once.
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

BasicUpstart2(start)

.macro Commit(i, source, volume, step) {
    lda shadow_step+i
    sta step+1
    lda shadow_volume+i
    sta volume+1
    lda shadow_reset+i
    beq !kept+
    lda shadow_start_lo+i
    sta source+1
    lda shadow_start_hi+i
    sta source+2
    lda shadow_loop_lo+i
    sta current_loop_lo+i
    lda shadow_loop_hi+i
    sta current_loop_hi+i
    lda #0
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
#if DIGI_DC_BOOST
    // Constant-DC reference on every voice: test + gate + pulse with pulse
    // width 0 and full sustain. The ADSR DAC then supplies a large fixed
    // voltage for the volume register to modulate, instead of the chip's
    // small natural offset. The voices stay untouched afterwards; the D418
    // sample stream and all SID oscillator playback states are unchanged.
    lda #$49
    sta SID+4
    sta SID+11
    sta SID+18
    lda #$01
    sta SID+5
    sta SID+12
    sta SID+19
    lda #$ff
    sta SID+6
    sta SID+13
    sta SID+20
#endif
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
    lda #200
    sta tick_error
    lda #0
    sta tick_error+1
    jsr prepare_tick_length
    lda next_tick_samples
    sta tick_samples
    jsr prepare_tick_length
    jsr decode_pending
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
    jsr prepare_tick_length
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

get_byte:
#if SCORE_DICTIONARY
    // Dictionary phrases are raw, non-recursive bytes. Only the foreground
    // decoder handles them; the sample IRQ and its timing are unchanged.
    lda phrase_remaining
    beq !stream+
    dec phrase_remaining
    php
    sei
    ldy #0
    lda (phrase_ptr),y
    plp
    inc phrase_ptr
    bne !ready+
    inc phrase_ptr+1
!ready:
    ora #0
    rts
!stream:
    jsr get_stream_byte
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
    php
    sei
    ldy #0
    lda (stream_ptr),y
    plp
    inc stream_ptr
    bne !ready+
    inc stream_ptr+1
!ready:
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
    sta shadow_start_lo+i
    lda bank_start_hi,x
    sta shadow_start_hi+i
    lda bank_loop_lo,x
    sta shadow_loop_lo+i
    lda bank_loop_hi,x
    sta shadow_loop_hi+i
!done:
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
    and #1
    beq !v0+
    :DecodeVoice(0)
!v0:
    lda voice_mask
    and #2
    beq !v1+
    :DecodeVoice(1)
!v1:
    lda voice_mask
    and #4
    beq !v2+
    :DecodeVoice(2)
!v2:
    lda voice_mask
    and #8
    beq !v3+
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
    cmp #5
    bcc !stagger+
    jmp mixer_begin
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
    cmp #4
    bne !check1+
    :Commit(0,read0,vol0,step0)
    jmp mixer_begin
!check1:
    cmp #3
    bne !check2+
    :Commit(1,read1,vol1,step1)
    jmp mixer_begin
!check2:
    cmp #2
    bne !check3+
    :Commit(2,read2,vol2,step2)
    jmp mixer_begin
!check3:
    :Commit(3,read3,vol3,step3)
mixer_begin:

read0:
    lda silence_sample
    bpl sample0
    cmp #$81
    bne loop0
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
    cmp #$81
    bne loop1
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
    cmp #$81
    bne loop2
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
    cmp #$81
    bne loop3
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

