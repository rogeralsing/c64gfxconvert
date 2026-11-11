// Bounded hybrid extension of the frozen MOD-channel oscillator sampler.
// Voice 3 keeps its reusable one-shot banks; voices 1/2 synthesize accompaniment.
// The NMI retains the reference's 126-cycle clock and clock-slide instructions.
.label fraction = $02
.label sample_index = $03
.label score_ptr = $04
.label boundary_count = $06
.label boundary_before = $07
.label underruns = $08
.label stop_requested = $09
.label generated_frames = $0a
.label next_buffer = $0c
.label pending_start_low = $0d
.label pending_sid = $0e

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
    ldx #17
!clear_state:
    sta $02,x
    dex
    bpl !clear_state-
    // The sample latch preserves A and P, leaving foreground X/Y untouched.
    ldx #0
!copy_nmi:
    lda nmi_image,x
    sta $80,x
    inx
    cpx #(nmi_end-nmi_entry)
    bne !copy_nmi-
    lda #<nmi_entry
    sta $fffa
    lda #>nmi_entry
    sta $fffb
    // Keep both ordinary envelopes quiet before enabling their waveforms.
    // TEST plus triangle establishes a known zero oscillator level at rest;
    // gate remains set across note changes, avoiding full-strength attacks.
    lda #0
    sta $d405
    sta $d40c
    lda #(SID1_SUSTAIN << 4)
    sta $d406
    lda #(SID2_SUSTAIN << 4)
    sta $d40d
    lda #<SID1_PULSE
    sta $d402
    lda #>SID1_PULSE
    sta $d403
    lda #0
    sta $d409
    lda #8
    sta $d40a
    lda #$19
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
    // Establish the same neutral floating level as the reference player.
    lda #128
    sta $d40f
    lda #9
    sta $d412
    lda #1
    sta $d412
    .fill 47, $ea
    lda #$11
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
    lda #<score
    sta score_ptr
    lda #>score
    sta score_ptr+1
    lda #>buffer_a
    sta destination+2
    jsr fill_frame
    jsr commit_sid
    lda pending_start_low
    sta buffer_read+1
    lda #>buffer_a
    sta buffer_read+2
    lda #125
    sta $dd04
    lda #0
    sta $dd05
    lda #$81
    sta $dd0d
    lda #$11
song_started:
    sta $dd0e
    lda #>buffer_b
    sta next_buffer

next_frame:
    lda boundary_count
    sta boundary_before
    lda next_buffer
    sta destination+2
    jsr fill_frame
    lda boundary_count
    cmp boundary_before
    beq !prepared+
    inc underruns
!prepared:
    // The NMI preserves X/Y and the wait loop only uses A. Preloading both
    // values here leaves just two stores in the narrow pointer-swap gap.
    ldx next_buffer
    ldy pending_start_low
wait_start:
    lda buffer_read+1
    bne wait_start
    // Reload the pointer before any other foreground work.
pointer_swap_begin:
    stx buffer_read+2
    sty buffer_read+1
pointer_commit:
    // The critical pointer stores have completed. SID writes remain fully
    // interruptible and apply only when their prepared PCM buffer is active.
    jsr commit_sid
    lda next_buffer
    eor #1
    sta next_buffer
    lda generated_frames
    cmp #<FRAME_COUNT
    bne next_frame
    lda generated_frames+1
    cmp #>FRAME_COUNT
    bne next_frame
    lda #1
    sta stop_requested
!wait_done:
    jmp !wait_done-

fill_begin:
fill_frame:
    // Eleven-byte score: the frozen five PCM fields, then two SID states
    // containing frequency low/high and control, without gate retriggers.
    // Each one-shot is page-padded with neutral values. All volume scaling
    // is already in its reusable bank, leaving the inner loop unchanged.
    ldy #0
    lda (score_ptr),y
    sta pitch+1
    iny
    lda (score_ptr),y
    beq !keep_sample+
    lda #0
    sta fraction
    sta sample_index
    iny
    lda (score_ptr),y
    sta source_read+2
    iny
    lda (score_ptr),y
    sta bank_end_compare+1
!keep_sample:
    ldy #4
    lda (score_ptr),y
    sta pending_start_low
    iny
    lda (score_ptr),y
    sta pending_sid
    iny
    lda (score_ptr),y
    sta pending_sid+1
    iny
    lda (score_ptr),y
    sta pending_sid+2
    iny
    lda (score_ptr),y
    sta pending_sid+3
    iny
    lda (score_ptr),y
    sta pending_sid+4
    iny
    lda (score_ptr),y
    sta pending_sid+5
    clc
    lda score_ptr
    adc #11
    sta score_ptr
    bcc !score_ready+
    inc score_ptr+1
!score_ready:
    ldx sample_index
    ldy pending_start_low
!render:
source_read:
    lda silence_page,x
destination:
    sta buffer_b,y
    lda fraction
    clc
pitch:
    adc #128
    sta fraction
    bcc !advanced+
    inx
    bne !advanced+
    lda source_read+2
    cmp #>silence_page
    beq !advanced+
    inc source_read+2
    lda source_read+2
bank_end_compare:
    cmp #>(silence_page+$100)
    bne !advanced+
    lda #>silence_page
    sta source_read+2
!advanced:
    iny
    bne !render-
    stx sample_index
    inc generated_frames
    bne !counted+
    inc generated_frames+1
!counted:
fill_end:
fill_frame_rts:
    rts

commit_sid:
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda pending_sid+3
    sta $d407
    lda pending_sid+4
    sta $d408
    lda pending_sid+5
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
    // Allow the emulator audio backend to flush the complete final buffer.
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

.align $100
nmi_image:
.pseudopc $80 {
nmi_entry:
    sta restore_a+1
    lda #125
    sec
    sbc $dd04
    sta jitter_branch+1
jitter_branch:
    bpl jitter_slide
jitter_slide:
    .fill 30, $a9
    .byte $ad, $a5, $ea
sample_latch:
    lda #$11
    sta $d412
    lda #$01
    sta $d412
    lda #$09
    sta $d412
buffer_read:
    lda buffer_a+$64
    sta $d40f
    lda #$01
    sta $d412
    inc buffer_read+1
    bne nmi_return
frame_boundary:
    inc boundary_count
    lda stop_requested
    beq nmi_return
    jmp finished
nmi_return:
    lda $dd0d
restore_a:
    lda #0
nmi_rti:
    rti
nmi_end:
}
.const NMI_BYTES = nmi_end-nmi_entry
.assert "NMI must fit in the allocated zero page", NMI_BYTES <= 128, true

.label buffer_a = $0200
.label buffer_b = $0300
.import source "data.asm"
