// Native one-PCM/triangle mixer plus two ordinary SID instruments.
// PCM banks are reusable fixed-pitch assets, with 156-byte end guards.
.import source "config.asm"
.label phase_low = $02
.label phase_high = $03
.label boundary_count = $06
.label boundary_before = $07
.label underruns = $08
.label generated_frames = $0a
.label next_buffer = $0c
.label pending_start_low = $0d
.label pending_sid = $0e
.label pcm_cursor = $11
.label pcm_old_base = $13
.label pending_gateoff = $15
.label target_buffer = $16
.label frame_count = $17
.label count_remainder = $18
.label pcm_active = $19
.label pcm_next = $1a
.label pcm_end = $1c
.label pcm_loop = $1e
.label pcm_base = $20
.label temp = $22
.label pending_flags = $24
.label buffer_a = $0200
.label buffer_b = $0300
.label neutral_pcm = $0700
.label nmi_entry = $dc04
.label nmi_rti = $dd0c

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
    sta $dc0f
    sta $dd0e
    sta $dd0f
    sta $d011
    sta $d015
    sta $d01a
    lda #$ff
    sta $d019
    lda #$35
    sta $01
    lda #0
    ldx #24
!clear_sid:
    sta $d400,x
    dex
    bpl !clear_sid-
    ldx #$2e
!clear_state:
    sta $02,x
    dex
    bpl !clear_state-
    lda #87
    sta count_remainder
    ldx #0
!neutral:
    lda #0
    sta $0600,x
    lda #113
    sta neutral_pcm,x
    inx
    bne !neutral-
!copy_handlers:
    lda normal_image,x
    sta $0400,x
    lda pending_image,x
    sta $0500,x
    inx
    bne !copy_handlers-
    ldx #0
!copy_nmi:
    lda nmi_image,x
    sta $80,x
    inx
    cpx #(nmi_end-nmi_common)
    bne !copy_nmi-
    lda #$40
    sta $dd0c
    lda #<nmi_entry
    sta $fffa
    lda #>nmi_entry
    sta $fffb
    lda #$4c
    sta $dc04
    jsr score_init
    jsr prefetch_next_tick
    lda #>buffer_a
    sta target_buffer
    jsr fill_frame
    jsr prefetch_next_tick
    jsr startup_audio_delay
    lda #0
    sta $d405
    sta $d40c
    lda voice_record+5
    and #SID1_MASK
    sta $d406
    lda voice_record+11
    and #SID2_MASK
    sta $d40d
    lda voice_record+3
    sta $d402
    lda voice_record+4
    sta $d403
    lda voice_record+9
    sta $d409
    lda voice_record+10
    sta $d40a
    lda #25
    sta $d404
    sta $d40b
    lda #0
    sta $d413
    lda #SID3_SUSTAIN
    sta $d414
    lda #1
    sta $d412
    lda #MASTER_VOLUME
    sta $d418
    lda #128
    sta $d40f
    lda #9
    sta $d412
    lda #1
    sta $d412
    .fill 47, $ea
    lda #17
    sta $d412
    lda #1
    sta $d412
    lda #0
    sta $d40f
    ldy #32
!warmup_outer:
    ldx #0
!warmup_inner:
    dex
    bne !warmup_inner-
    dey
    bne !warmup_outer-
    jsr startup_initial_delay
    lda pending_start_low
    sta buffer_read+1
    lda #>buffer_a
    sta buffer_read+2
    jsr commit_extra_sid
    jsr commit_sid1
    bit $ea
    .fill 8, $ea
    .fill 3, $ea
    bit $ea
    .fill 3, $ea
    lda #0
    sta $dc05
    lda #125
    sta $dc06
    lda #0
    sta $dc07
    lda #125
    sta $dd04
    lda #0
    sta $dd05
    lda #$81
    sta $dd0d
    lda #$11
song_started:
    sta $dd0e
    sta $dc0f
    lda #>buffer_b
    sta next_buffer
next_frame:
    lda boundary_count
    sta boundary_before
    lda next_buffer
    sta target_buffer
    jsr fill_frame
    lda boundary_count
    cmp boundary_before
    beq !prepared+
    inc underruns
    bne !prepared+
    inc underruns+1
!prepared:
    lda generated_frames
    cmp #<FRAME_COUNT
    bne !prefetch+
    lda generated_frames+1
    cmp #>FRAME_COUNT
    beq !already_final+
!prefetch:
    jsr prefetch_next_tick
!already_final:
wait_start:
    lda boundary_count
    cmp boundary_before
    beq wait_start
!sid1_committed:
    lda sid_dispatch+2
    cmp #>normal_handler
    bne !sid1_committed-
    jsr commit_extra_sid
    lda next_buffer
    eor #1
    sta next_buffer
    lda generated_frames
    cmp #<FRAME_COUNT
    bne next_frame
    lda generated_frames+1
    cmp #>FRAME_COUNT
    bne next_frame
    lda #<finished
    sta boundary_stop_jump+1
    lda #>finished
    sta boundary_stop_jump+2
!wait_done:
    jmp !wait_done-

fill_begin:
fill_frame:
    jsr synth_sid_tick
    lda tick_record+23
    sta pending_flags
    lda #156
    sta frame_count
    lda count_remainder
    clc
    adc #68
    cmp #175
    bcc !count_ready+
    sbc #175
    inc frame_count
!count_ready:
    sta count_remainder
    lda #0
    sec
    sbc frame_count
    sta pending_start_low
    lda tick_record+15
    beq !bass_hold+
    lda #0
    sta phase_low
    sta phase_high
!bass_hold:
    // Retain the playing control before preparing the next one. Continuous
    // SID1 envelopes repeat this value at the boundary, without a new edge.
    lda pending_sid+2
    sta pending_gateoff
    lda voice_record
    and #SID1_MASK
    sta pending_sid
    lda voice_record+1
    and #SID1_MASK
    sta pending_sid+1
    lda voice_record+2
    and #SID1_MASK
    ora #SID1_TEST
    sta pending_sid+2
    lda tick_record+1
    and #1
    bne !sid1_envelope_held+
    lda pending_flags
    and #1
    beq !sid1_hold+
    lda pending_sid+2
    and #254
    jmp !sid1_off_ready+
!sid1_hold:
    lda pending_sid+2
!sid1_off_ready:
    sta pending_gateoff
!sid1_envelope_held:
    jsr prepare_pcm
    lda pending_flags
    and #12
    lsr
    lsr
    tax
    lda patch_low,x
    sta patch_dispatch+1
    lda patch_high,x
    sta patch_dispatch+2
    lda kernel_low,x
    sta mix_call+1
    lda kernel_high,x
    sta mix_call+2
patch_dispatch:
    jsr patch_full
    clc
mix_call:
    jsr mix_samples
    jsr advance_pcm
    inc generated_frames
    bne !counted+
    inc generated_frames+1
!counted:
fill_end:
fill_frame_rts:
    rts

// Exactly one decoded tick is held ahead; physical SID fields and PCM metadata
// are already copied before the following score can overwrite tick_record.
prefetch_next_tick:
score_prefetch_begin:
    jsr score_next_tick
score_prefetch_end:
    rts

// A base change preserves elapsed position, e.g. a reused gain bank.
prepare_pcm:
    lda tick_record+16
    sta pcm_base
    lda tick_record+17
    sta pcm_base+1
    ora pcm_base
    beq pcm_off
    lda tick_record+18
    sta pcm_end
    lda tick_record+19
    sta pcm_end+1
    lda tick_record+20
    sta pcm_loop
    lda tick_record+21
    sta pcm_loop+1
    lda tick_record+22
    beq !held+
    lda #1
    sta pcm_active
    lda pcm_base
    sta pcm_cursor
    lda pcm_base+1
    sta pcm_cursor+1
    jmp !base_ready+
!held:
    lda pcm_active
    beq pcm_off
    sec
    lda pcm_cursor
    sbc pcm_old_base
    sta temp
    lda pcm_cursor+1
    sbc pcm_old_base+1
    sta temp+1
    clc
    lda pcm_base
    adc temp
    sta pcm_cursor
    lda pcm_base+1
    adc temp+1
    sta pcm_cursor+1
!base_ready:
    lda pcm_base
    sta pcm_old_base
    lda pcm_base+1
    sta pcm_old_base+1
    rts
pcm_off:
    lda #0
    sta pcm_active
    lda #<neutral_pcm
    sta pcm_cursor
    lda #>neutral_pcm
    sta pcm_cursor+1
    rts

// Guards supply a contiguous crossing tick. Resolve at most one loop wrap.
// The reusable bank must have loop length >=157, and 156 guard bytes.
advance_pcm:
    lda pcm_active
    beq !done+
    clc
    lda pcm_cursor
    adc frame_count
    sta pcm_next
    lda pcm_cursor+1
    adc #0
    sta pcm_next+1
    sec
    lda pcm_next
    sbc pcm_end
    sta temp
    lda pcm_next+1
    sbc pcm_end+1
    sta temp+1
    bcc !next+
    lda pcm_loop
    ora pcm_loop+1
    beq pcm_off
    clc
    lda pcm_loop
    adc temp
    sta pcm_next
    lda pcm_loop+1
    adc temp+1
    sta pcm_next+1
!next:
    lda pcm_next
    sta pcm_cursor
    lda pcm_next+1
    sta pcm_cursor+1
!done:
    rts

commit_sid1:
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    rts
commit_extra_sid:
    lda voice_record+3
    sta $d402
    lda voice_record+4
    sta $d403
    lda voice_record+5
    and #SID1_MASK
    sta $d406
    lda voice_record+8
    and #SID2_MASK
    ora #SID2_TEST
    sta temp
    lda pending_flags
    and #2
    beq !sid2_hold+
    lda temp
    and #254
    jmp !sid2_off_ready+
!sid2_hold:
    lda temp
!sid2_off_ready:
    sta $d40b
    lda voice_record+6
    and #SID2_MASK
sid2_low_store:
    sta $d407
    lda voice_record+7
    and #SID2_MASK
sid2_high_store:
    sta $d408
    lda voice_record+8
    and #SID2_MASK
    ora #SID2_TEST
sid2_control_store:
    sta $d40b
    lda voice_record+9
    sta $d409
    lda voice_record+10
    sta $d40a
    lda voice_record+11
    and #SID2_MASK
    sta $d40d
    rts
finished:
    sei
    lda #0
    sta $dd0e
    lda #$7f
    sta $dd0d
    lda $dd0d
    lda #0
    sta $d404
    sta $d40b
    sta $d412
    sta $d418
    ldy #80
!tail_outer:
    ldx #0
!tail_inner:
    dex
    bne !tail_inner-
    dey
    bne !tail_outer-
done:
    jmp done
runtime_end:
.assert "Main runtime must stay below asset data", runtime_end <= $1000, true
.assert "The full-length prefetch player needs at least two ticks", FRAME_COUNT > 1, true
.import source "data.asm"
.import source "score.asm"
.import source "sid-programs.asm"
.for (var page=$70;page<=$78;page++) {
    .pc = page*$100 "Distributed jitter entry"
    .var delta=page-$70
    .fill floor(delta/2),$ea
    .if (mod(delta,2)==0) { .byte $85,<(restore_a+1) }
    else { .byte $8d,<(restore_a+1),>(restore_a+1) }
    jmp nmi_common
}
.import source "mix.asm"
.import source "patch.asm"
.import source "delays.asm"
.pc = $7d00 "Normal interrupt template"
normal_image:
.pseudopc $0400 {
normal_handler:
    .byte $e6, <(buffer_read+1)
    bne !return+
    jmp frame_boundary
!return:
    .byte $a5, <(restore_a+1)
    jmp $dd0c
    .fill $0500-*, $ea
}
.pc = $7e00 "Pending SID1 interrupt template"
pending_image:
.pseudopc $0500 {
pending_handler:
    bit $ea
    .fill 7, $ea
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda #>normal_handler
    .byte $85, <(sid_dispatch+2)
    .byte $e6, <(buffer_read+1)
    .byte $a5, <(restore_a+1)
    jmp $dd0c
    .fill $0600-*, $ea
}
.pc = $7f00 "Zero-page interrupt template"
nmi_image:
.pseudopc $80 {
nmi_common:
sample_latch:
    lda #17
    sta $d412
    lda #1
    sta $d412
    lda #9
    sta $d412
buffer_read:
    lda buffer_a+$64
    sta $d40f
    lda #1
    sta $d412
sid_dispatch:
    jmp normal_handler
frame_boundary:
    inc boundary_count
    .byte $e6, <(sid_dispatch+2)
boundary_stop_jump:
    jmp activate_buffer
activate_buffer:
    lda pending_gateoff
    sta $d404
pointer_swap_begin:
    lda next_buffer
    .byte $85, <(buffer_read+2)
pointer_ready_read:
    lda pending_start_low
pointer_low_store:
    .byte $85, <(buffer_read+1)
nmi_return:
restore_a:
    lda #0
    jmp $dd0c
nmi_end:
}
.assert "Runtime auxiliary area must stay below 8000", * <= $8000, true
