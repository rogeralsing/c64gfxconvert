// Full-song extension: packed state streams, per-frame gain banks and loops.
// Voice 3 still uses the frozen 126-cycle oscillator sample-and-hold NMI.
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
.label cursor_page = $14
.label bank_base = $15
.label source_muted = $16
.label sample_ended = $17
.label clock_index = $18
.label chunk_offset = $19
.label current_variant = $1a
.label retrigger = $1b

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
    ldx #$1b
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
    lda #<SID2_PULSE
    sta $d409
    lda #>SID2_PULSE
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
    lda #12
    sta chunk_offset
    lda #$ff
    sta current_variant
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
    // Three independent state streams share twelve-tick chunk pointers.
    // Every PCM trigger remains an action, even when a state ID repeats.
    lda chunk_offset
    cmp #12
    bne !chunk_ready+
    jsr load_chunk
!chunk_ready:
    ldy chunk_offset
pcm_chunk_read:
    ldx pcm_chunk_0,y
    lda pcm_step,x
    sta pitch+1
    lda pcm_trigger,x
    sta retrigger
    lda pcm_variant,x
    sta source_muted
    and #$7f
    cmp current_variant
    beq !bank_ready+
    sta current_variant
    tax
    lda bank_base_hi,x
    sta bank_base
    lda bank_end_lo,x
    sta end_check+1
    lda bank_end_hi,x
    sta bank_end_page+1
    lda bank_loop_lo,x
    sta loop_index+1
    lda bank_loop_hi,x
    sta loop_page+1
!bank_ready:
    ldy chunk_offset
lead_chunk_read:
    ldx lead_chunk_0,y
    lda lead_low,x
    sta pending_sid
    lda lead_high,x
    sta pending_sid+1
    lda lead_control,x
    sta pending_sid+2
bass_chunk_read:
    ldx bass_chunk_0,y
    lda bass_low,x
    sta pending_sid+3
    lda bass_high,x
    sta pending_sid+4
    lda bass_control,x
    sta pending_sid+5
    inc chunk_offset
    ldx clock_index
    lda frame_start_low,x
    sta pending_start_low
    inx
    cpx #175
    bne !clock_ready+
    ldx #0
!clock_ready:
    stx clock_index
    lda retrigger
    beq !cursor_ready+
    lda #0
    sta fraction
    sta sample_index
    sta cursor_page
    sta sample_ended
    jsr select_end_branch
!cursor_ready:
    lda sample_ended
    beq !not_ended+
    lda #0
    sta pitch+1
    beq !constant+
!not_ended:
    lda source_muted
    bmi !constant+
    lda #$bd
    sta source_read
    lda #0
    sta source_read+1
    lda bank_base
    clc
    adc cursor_page
    sta source_read+2
    jmp !render_ready+
!constant:
    jsr constant_read
!render_ready:
    ldx sample_index
    ldy pending_start_low
!render:
source_read:
    lda $1000,x
    // Muting patches the same three bytes to LDA #128; NOP. Both paths
    // take four cycles. The logical cursor continues without stray RAM reads.
destination:
    sta buffer_b,y
    lda fraction
    clc
pitch:
    adc #128
    sta fraction
    bcc render_advanced
    inx
source_nonwrap:
    bne render_advanced
    jmp page_advanced
end_check:
    cpx #0
    bne render_advanced
    jmp end_reached
render_advanced:
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

page_advanced:
    inc cursor_page
    lda cursor_page
bank_end_page:
    cmp #0
    bne !page_ready+
    lda end_check+1
    beq end_reached
    jsr select_end_branch
!page_ready:
    jsr update_read_page
    jmp render_advanced

end_reached:
loop_page:
    lda #$ff
    cmp #$ff
    beq !one_shot+
    sta cursor_page
loop_index:
    ldx #0
    jsr select_end_branch
    jsr update_read_page
    jmp render_advanced
!one_shot:
    lda #1
    sta sample_ended
    lda #0
    sta pitch+1
    jsr constant_read
    jmp render_advanced

select_end_branch:
    // Page-rounded one-shots add no per-source-byte comparison. Exact loop
    // endpoints are compared only while the cursor occupies their last page.
    lda #<(render_advanced-(source_nonwrap+2))
    sta source_nonwrap+1
    lda end_check+1
    beq !selected+
    lda cursor_page
    cmp bank_end_page+1
    bne !selected+
    lda #<(end_check-(source_nonwrap+2))
    sta source_nonwrap+1
!selected:
    rts

update_read_page:
    lda source_read
    cmp #$bd
    bne !updated+
    lda bank_base
    clc
    adc cursor_page
    sta source_read+2
!updated:
    rts

constant_read:
    lda #$a9
    sta source_read
    lda #128
    sta source_read+1
    lda #$ea
    sta source_read+2
    rts

load_chunk:
    ldy #0
    lda (score_ptr),y
    sta pcm_chunk_read+1
    iny
    lda (score_ptr),y
    sta pcm_chunk_read+2
    iny
    lda (score_ptr),y
    sta lead_chunk_read+1
    iny
    lda (score_ptr),y
    sta lead_chunk_read+2
    iny
    lda (score_ptr),y
    sta bass_chunk_read+1
    iny
    lda (score_ptr),y
    sta bass_chunk_read+2
    clc
    lda score_ptr
    adc #6
    sta score_ptr
    bcc !playlist_ready+
    inc score_ptr+1
!playlist_ready:
    lda #0
    sta chunk_offset
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

runtime_end:

.label buffer_a = $0200
.label buffer_b = $0300
.import source "data.asm"
