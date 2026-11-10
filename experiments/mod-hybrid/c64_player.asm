// PAL C64 prototype: 2 SID + 2 PCM, or 3 SID + 1 PCM through $D418.
// PCM IRQ rate is 985248 / 256 = 3848.625 Hz. The global volume DAC also
// modulates both SID tones; the first hardware target is the original 6581.

.label SID = $d400
.label P0 = $20
.label P1 = $30
.label mix0 = $40
.label mix1 = $41
.label next_dac = $42
.label tick_samples = $43
.label next_tick_samples = $44
.label tick_due = $45
.label tick_error = $46
.label played_tick_count = $48
.label underrun_counter = $4a
.label stream_ptr = $50
.label playlist_ptr = $52
.label hold_ticks = $54
.label field_flags = $55
.label voice_mask = $56
.label retrigger = $57

BasicUpstart2(start)

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
    ldx #$37
    lda #0
!clear:
    sta $20,x
    dex
    bpl !clear-
    ldx #24
!sid_clear:
    sta SID,x
    dex
    bpl !sid_clear-
    .if (PCM_COUNT == 1) {
        lda #12
    } else {
        lda #8
    }
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
    jsr sequence_tick
    // Bresenham sample counts: 30789/400 samples per 50 Hz tick. A midpoint
    // accumulator rounds cumulative musical time to the nearest PCM sample.
    lda #200
    sta tick_error
    lda #0
    sta tick_error+1
    jsr prepare_tick_length
    lda next_tick_samples
    sta tick_samples
    jsr prepare_tick_length
    sei
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
main_wait:
    lda tick_due
    beq main_wait
    dec tick_due
    jsr prepare_tick_length
    jsr sequence_tick
    jmp main_wait

done:
    sei
    lda #0
    sta $dc0e
    sta SID+4
    sta SID+11
    sta SID+18
    sta SID+24
    lda #$7f
    sta $dc0d
    lda $dc0d
    lda #5
    sta $d020
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
    ldy #0
    lda (stream_ptr),y
    inc stream_ptr
    bne !got+
    inc stream_ptr+1
!got:
    // The caller branches on the returned command, not the pointer increment.
    ora #0
    rts

next_block:
    ldy #0
    lda (playlist_ptr),y
    sta stream_ptr
    iny
    lda (playlist_ptr),y
    sta stream_ptr+1
    ora stream_ptr
    bne !present+
    jmp done
!present:
    clc
    lda playlist_ptr
    adc #2
    sta playlist_ptr
    bcc !ready+
    inc playlist_ptr+1
!ready:
    rts

.macro ReadSid(index, offset) {
    lda #0
    sta retrigger
    jsr get_byte
    sta field_flags
    and #1
    beq !freq_done+
    jsr get_byte
    sta SID+offset
    jsr get_byte
    sta SID+offset+1
!freq_done:
    lda field_flags
    and #2
    beq !volume_done+
    jsr get_byte
    cmp sid_volume+index
    bcc !not_rising+
    beq !not_rising+
    inc retrigger
!not_rising:
    sta sid_volume+index
!volume_done:
    lda field_flags
    and #4
    beq !wave_done+
    jsr get_byte
    sta sid_wave+index
!wave_done:
    lda field_flags
    and #8
    beq !pulse_done+
    jsr get_byte
    sta SID+offset+2
    jsr get_byte
    sta SID+offset+3
!pulse_done:
    lda field_flags
    and #16
    ora retrigger
    beq !keep_gate+
    lda #0
    sta SID+offset+4
!keep_gate:
    lda #0
    sta SID+offset+5
    lda sid_volume+index
    asl
    asl
    asl
    asl
    sta SID+offset+6
    lda sid_volume+index
    beq !muted+
    lda sid_wave+index
    ora #1
!muted:
    sta SID+offset+4
}

.macro ReadPcm(index, state) {
    jsr get_byte
    sta field_flags
    and #1
    beq !sample_done+
    jsr get_byte
    sta pcm_id+index
!sample_done:
    lda field_flags
    and #2
    beq !step_done+
    jsr get_byte
    sta pcm_step_lo+index
    jsr get_byte
    sta pcm_step_hi+index
!step_done:
    lda field_flags
    and #4
    beq !volume_done+
    jsr get_byte
    asl
    asl
    asl
    asl
    sta pcm_volume+index
!volume_done:
    // Only the short state commit is atomic. Byte-stream decoding remains
    // interruptible so the sample timer keeps running during large packets.
    sei
    lda pcm_step_lo+index
    sta state+3
    lda pcm_step_hi+index
    sta state+4
    lda pcm_volume+index
    sta state+11
    ldx pcm_id+index
    bne !has_sample+
    lda #0
    sta state+10
    jmp !committed+
!has_sample:
    lda field_flags
    and #8
    beq !committed+
    lda bank_start_lo,x
    sta state
    lda bank_start_hi,x
    sta state+1
    lda bank_end_lo,x
    sta state+5
    lda bank_end_hi,x
    sta state+6
    lda bank_loop_lo,x
    sta state+7
    lda bank_loop_hi,x
    sta state+8
    lda bank_loop_enabled,x
    sta state+9
    lda #0
    sta state+2
    lda #1
    sta state+10
!committed:
    cli
}

sequence_tick:
    lda hold_ticks
    beq !command+
    dec hold_ticks
    jmp !counted+
!command:
    jsr get_byte
    bne !not_end+
    jsr next_block
    jmp !command-
!not_end:
    bmi !packet+
    sec
    sbc #1
    sta hold_ticks
    jmp !counted+
!packet:
    sta voice_mask
    and #1
    beq !sid0_done+
    :ReadSid(0, 0)
!sid0_done:
    lda voice_mask
    and #2
    beq !sid1_done+
    :ReadSid(1, 7)
!sid1_done:
    .if (SID_COUNT == 3) {
        lda voice_mask
        and #4
        beq !sid2_done+
        :ReadSid(2, 14)
    !sid2_done:
    }
    lda voice_mask
    and #(1 << SID_COUNT)
    beq !pcm0_done+
    :ReadPcm(0, P0)
!pcm0_done:
    .if (PCM_COUNT == 2) {
    lda voice_mask
    and #8
    beq !pcm1_done+
    :ReadPcm(1, P1)
!pcm1_done:
    }
!counted:
    inc played_tick_count
    bne !return+
    inc played_tick_count+1
!return:
    rts

// The IRQ reads one 4-bit sample byte per voice before advancing its 8.8
// position. End comparison is exact, including overshoot into a repeated loop.
.macro MixPcm(state, destination) {
    lda state+10
    bne !active+
    .if (PCM_COUNT == 1) {
        lda #12
    } else {
        lda #4
    }
    sta destination
    jmp !mixed+
!active:
    ldy #0
    lda (state),y
    ora state+11
    tax
    lda pcm_volume_table,x
    sta destination
    clc
    lda state+2
    adc state+3
    sta state+2
    lda state
    adc state+4
    sta state
    lda state+1
    adc #0
    sta state+1
    cmp state+6
    bcc !mixed+
    bne !ended+
    lda state
    cmp state+5
    bcc !mixed+
!ended:
    lda state+9
    bne !loop+
    lda #0
    sta state+10
    jmp !mixed+
!loop:
    sec
    lda state
    sbc state+5
    sta state
    lda state+1
    sbc state+6
    sta state+1
    clc
    lda state
    adc state+7
    sta state
    lda state+1
    adc state+8
    sta state+1
!mixed:
}

irq:
    pha
    txa
    pha
    tya
    pha
    lda $dc0d
    // Output comes before variable endpoint/loop work, minimizing DAC jitter.
    lda next_dac
    sta SID+24
    :MixPcm(P0, mix0)
    .if (PCM_COUNT == 2) {
        :MixPcm(P1, mix1)
        clc
        lda mix0
        adc mix1
    } else {
        lda mix0
    }
    sta next_dac
    dec tick_samples
    bne !no_tick+
    lda next_tick_samples
    sta tick_samples
    inc tick_due
    lda tick_due
    cmp #2
    bcc !no_tick+
    inc underrun_counter
    bne !no_tick+
    inc underrun_counter+1
!no_tick:
    pla
    tay
    pla
    tax
    pla
    rti

sid_wave: .fill SID_COUNT, $40
sid_volume: .fill SID_COUNT, 0
pcm_id: .fill PCM_COUNT, 0
pcm_step_lo: .fill PCM_COUNT, 0
pcm_step_hi: .fill PCM_COUNT, 0
pcm_volume: .fill PCM_COUNT, 0
player_end:
