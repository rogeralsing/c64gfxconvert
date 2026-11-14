// Diagnostic only: accepted C1 triangle + C4 drums on SID3, C2 on SID1.
// Original C3 is intentionally absent. SID2 exercises ordinary TEST states.
.label phase_low = $02
.label phase_high = $03
.label score_ptr = $04
.label boundary_count = $06
.label boundary_before = $07
.label underruns = $08
.label generated_frames = $0a
.label next_buffer = $0c
.label pending_start_low = $0d
.label pending_sid = $0e
.label drum_elapsed = $14
.label frame_count = $16
.label source_work = $17
.label buffer_a = $0200
.label buffer_b = $0300
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
    ldx #20
!clear_state:
    sta $02,x
    dex
    bpl !clear_state-
    ldx #0
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
    lda #<score
    sta score_ptr
    lda #>score
    sta score_ptr+1
    lda #>buffer_a
    sta destination0+2
    jsr fill_frame
    jsr startup_audio_delay
    lda #0
    sta $d405
    sta $d40c
    lda #(SID1_SUSTAIN << 4)
    sta $d406
    lda #0
    sta $d40d
    lda #<1966
    sta $d402
    lda #>1966
    sta $d403
    lda #0
    sta $d409
    lda #8
    sta $d40a
    lda #25
    sta $d404
    sta $d40b
    lda #0
    sta $d413
    lda #$f0
    sta $d414
    lda #1
    sta $d412
    lda #15
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
    // Keep startup spacing independent of the removed SID2 sampler.
    lda #0
    sta $d408
    lda #25
    sta $d40b
    lda #25
    sta $d40b
    .fill 119, $ea
    lda #25
    sta $d40b
    lda #25
    sta $d40b
    ldy #32
!warmup_outer:
    ldx #0
!warmup_inner:
    dex
    bne !warmup_inner-
    dey
    bne !warmup_outer-
    jsr commit_sid2
    jsr startup_initial_delay
    lda pending_start_low
    sta buffer_read+1
    lda #>buffer_a
    sta buffer_read+2
    lda #0
    sta $d408
    jsr commit_sid1
    bit $ea
    .fill 8, $ea
    lda #25
    sta $d40b
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
    sta destination0+2
    jsr fill_frame
    lda boundary_count
    cmp boundary_before
    beq !prepared+
    inc underruns
!prepared:
wait_start:
    lda boundary_count
    cmp boundary_before
    beq wait_start
!sid1_committed:
    lda sid_dispatch+2
    cmp #>normal_handler
    bne !sid1_committed-
    jsr commit_sid2
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

// Native phase and note cursors; the score contains no mixed waveform.
fill_begin:
fill_frame:
    ldy #0
    lda (score_ptr),y
    .for (var i=0; i<5; i++) { sta step_low[i]+1 }
    iny
    lda (score_ptr),y
    .for (var i=0; i<5; i++) { sta step_high[i]+1 }
    iny
    lda (score_ptr),y
    .for (var i=0; i<5; i++) { sta triangle_read[i]+2 }
    ldy #4
    lda (score_ptr),y
    beq !drum_hold+
    lda #0
    sta drum_elapsed
    sta drum_elapsed+1
!drum_hold:
    dey
    lda (score_ptr),y
    tax
    beq !neutral+
    clc
    lda drum_virtual_low,x
    adc drum_elapsed
    sta source_work
    lda drum_virtual_high,x
    adc drum_elapsed+1
    sta source_work+1
    jmp !source_ready+
!neutral:
    lda drum_virtual_low
    sta source_work
    lda drum_virtual_high
    sta source_work+1
!source_ready:
    lda source_work
    .for (var i=0; i<5; i++) { sta sample_read[i]+1 }
    lda source_work+1
    .for (var i=0; i<5; i++) { sta sample_read[i]+2 }
    ldy #5
    lda (score_ptr),y
    sta pending_start_low
    .for (var i=0; i<5; i++) { sta destination[i]+1 }
    eor #$ff
    clc
    adc #1
    sta frame_count
    sta mix_end_count+1
    lda destination0+2
    .for (var i=1; i<5; i++) { sta destination[i]+2 }
    iny
    lda (score_ptr),y
    beq !bass_hold+
    lda #0
    sta phase_low
    sta phase_high
!bass_hold:
    ldy #7
    .for (var field=0; field<6; field++) {
        lda (score_ptr),y
        sta pending_sid+field
        iny
    }
    clc
    lda score_ptr
    adc #13
    sta score_ptr
    bcc !score_ready+
    inc score_ptr+1
!score_ready:
    clc
    jsr mix_samples
    clc
    lda drum_elapsed
    adc frame_count
    sta drum_elapsed
    bcc !position+
    inc drum_elapsed+1
!position:
    inc generated_frames
    bne !counted+
    inc generated_frames+1
!counted:
fill_end:
fill_frame_rts:
    rts
commit_sid1:
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    rts
commit_sid2:
    lda pending_sid+3
sid2_low_store:
    sta $d407
    lda pending_sid+4
sid2_high_store:
    sta $d408
    lda pending_sid+5
sid2_control_store:
    sta $d40b
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
.align $100
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
runtime_end:
.assert "Bootstrap must stay below instrument data", runtime_end <= $1000, true
.import source "data.asm"
.for (var page=$70;page<=$78;page++) {
    .pc = page*$100 "Unchanged distributed jitter entry"
    .var delta=page-$70
    .fill floor(delta/2),$ea
    .if (mod(delta,2)==0) { .byte $85,<(restore_a+1) }
    else { .byte $8d,<(restore_a+1),>(restore_a+1) }
    jmp nmi_common
}
.import source "mix.asm"
.import source "delays.asm"
