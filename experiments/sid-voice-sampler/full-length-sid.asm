// Native50Hz SID instrument programs. Decoder records remain immutable.
// X=0/6 selects each six-byte voice; ZP60..61 are foreground scratch only.
.label voice_record = $0620
.label sid_age = $062c
.label sid_arp = $062d
.label sid_id = $60
.label sid_gate_mask = $61

synth_sid_tick:
    ldx #0
    jsr synth_sid_voice
    // The accepted SID1 recipe holds sustain through TEST rests. It must not
    // discharge the envelope when only the waveform is being silenced.
    lda tick_record+1
    and #1
    beq !sid1_envelope_ready+
    lda tick_record+5
    asl
    asl
    asl
    asl
    sta voice_record+5
!sid1_envelope_ready:
    ldx #6
synth_sid_voice:
    lda #1
    cpx #0
    beq !mask_ready+
    asl
!mask_ready:
    sta sid_gate_mask
    and tick_record+23
    beq !advance+
    lda #0
    sta sid_age,x
    sta sid_arp,x
    beq !age_ready+
!advance:
    lda sid_age,x
    cmp #255
    beq !age_saturated+
    inc sid_age,x
!age_saturated:
    inc sid_arp,x
    lda sid_arp,x
    cmp #3
    bcc !age_ready+
    lda #0
    sta sid_arp,x
!age_ready:
    lda tick_record+2,x
    and #127
    tay
    sta sid_id
    lda sid_pulse_low,y
    sta voice_record+3,x
    lda sid_pulse_high,y
    sta voice_record+4,x
    lda tick_record+2,x
    bmi !active+
    jmp sid_voice_off
!active:
    lda sid_durations,y
    beq !not_expired+
    cmp sid_age,x
    bcc !expired+
    beq !expired+
!not_expired:
    lda sid_controls,y
    bne !has_wave+
!expired:
    jmp sid_voice_off
!has_wave:
    sta voice_record+2,x
    lda tick_record+5,x
    asl
    asl
    asl
    asl
    sta voice_record+5,x
    ldy tick_record,x
    lda sid_frequency_low,y
    sta voice_record,x
    lda sid_frequency_high,y
    sta voice_record+1,x
    ldy sid_id
    lda sid_chords,y
    beq !not_chord+
    lda #>sid_trio_low
    clc
    adc tick_record+4,x
    sta sid_trio_read_low+2
    lda #>sid_trio_high
    clc
    adc tick_record+4,x
    sta sid_trio_read_high+2
    lda tick_record+3,x
    clc
    adc sid_arp,x
    tay
sid_trio_read_low:
    lda sid_trio_low,y
    sta voice_record,x
sid_trio_read_high:
    lda sid_trio_high,y
    sta voice_record+1,x
    rts
!not_chord:
    cpy #2
    bne !not_kick+
    lda sid_age,x
    bne !kick_not_initial+
    jmp sid_double_twice
!kick_not_initial:
    cmp #1
    bne !kick_return+
    jmp sid_double_once
!kick_return:
    rts
!not_kick:
    cpy #5
    beq !wood+
    cpy #6
    bne !not_wood+
!wood:
    lda sid_age,x
    bne !wood_return+
    jmp sid_double_once
!wood_return:
    rts
!not_wood:
    cpy #14
    bne !not_lead14+
    lda #<700
    sta voice_record+3,x
    lda #>700
    sta voice_record+4,x
    lda sid_age,x
    cmp #2
    bcc !return+
    lda #33
    sta voice_record+2,x
!return:
    rts
!not_lead14:
    cpy #23
    bne !not_lead23+
    lda sid_age,x
    cmp #2
    bcs !lead23_pulse+
    lda #33
    sta voice_record+2,x
!lead23_pulse:
    lda sid_age,x
    lsr
    lsr
    and #3
    tay
    lda sid_lead23_pulse_low,y
    sta voice_record+3,x
    lda sid_lead23_pulse_high,y
    sta voice_record+4,x
    rts
!not_lead23:
    cpy #17
    bcc !return+
    cpy #23
    bcs !return+
    lda #129
    ldy sid_age,x
    beq !special_wave+
    lda #33
!special_wave:
    sta voice_record+2,x
    lda voice_record+5,x
    cpy #6
    bcc !special_level+
    sec
    sbc #16
    bcc !special_zero+
    cpy #12
    bcc !special_level+
    sec
    sbc #16
    bcs !special_level+
!special_zero:
    lda #0
!special_level:
    sta voice_record+5,x
    rts

sid_voice_off:
    lda #0
    sta voice_record,x
    sta voice_record+1,x
    sta voice_record+5,x
    lda #25
    sta voice_record+2,x
    rts
sid_double_twice:
    jsr sid_double_once
sid_double_once:
    asl voice_record,x
    rol voice_record+1,x
    bcc !return+
    lda #255
    sta voice_record,x
    sta voice_record+1,x
!return:
    rts
sid_lead23_pulse_low:
    .byte <1100,<1500,<1966,<2200
sid_lead23_pulse_high:
    .byte >1100,>1500,>1966,>2200
