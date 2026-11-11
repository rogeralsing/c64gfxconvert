// Independent SounDemoN-method experiment. No PCM writes to $d418.
// Inspired by the mechanism explained in Linus Akesson's Platform Hopping:
// https://linusakesson.net/music/platform-hopping/index.php
// Voice 3 latches triangle-wave levels; voices 1/2 remain ordinary synths.
.label fraction = $02
.label sample_index = $03
.label score_ptr = $04
.label boundary_count = $06
.label boundary_before = $07
.label underruns = $08
.label stop_requested = $09
.label generated_frames = $0a
.label next_buffer = $0c
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
    // Install our small NMI handler in zero page; it preserves A and P.
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
    lda #0
    sta $d405
    sta $d40c
    sta $d413
    // The sample voice keeps its envelope open across all sample values.
    lda #$f0
    sta $d414
    lda #1
    sta $d412
    lda #$30
    sta $d406
    lda #$20
    sta $d40d
    // Warm up the quiet sustain levels while the waveforms are disabled.
    // Later waveform enable must not retrigger a full-volume attack.
    lda #1
    sta $d404
    sta $d40b
    lda #8
    sta $d403
    sta $d40a
    lda #15
    sta $d418
    // Establish a neutral floating level before the recording starts.
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
    // Let the initial 2 ms attack settle before starting the sample clock.
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
    lda #$64
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
!wait_boundary:
    lda buffer_read+1
    bne !wait_boundary-
    // There is one NMI-free gap to replace the consumed buffer pointer.
    lda next_buffer
    sta buffer_read+2
    lda #$64
    sta buffer_read+1
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

fill_frame:
    // Score entries: fractional pitch, retrigger, two frequencies/controls.
    ldy #0
    lda (score_ptr),y
    sta pitch+1
    iny
    lda (score_ptr),y
    beq !keep_sample+
    lda #0
    sta fraction
    sta sample_index
    lda #>guitar_bank
    sta source_read+2
!keep_sample:
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
    adc #8
    sta score_ptr
    bcc !score_ready+
    inc score_ptr+1
!score_ready:
    ldx sample_index
    ldy #$64
!render:
source_read:
    lda guitar_bank,x
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
    cmp #>guitar_end
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
    rts

commit_sid:
    // Apply the prepared synth state when its PCM buffer becomes active.
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
    // Run a short silent tail so VICE's audio backend flushes the full phrase
    // before the monitor completion breakpoint is reached.
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
    // Branch into a clock slide using the live CIA countdown. The slide
    // cancels instruction-boundary NMI latency before the amplitude latch.
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
    inc boundary_count
    lda stop_requested
    beq nmi_return
    jmp finished
nmi_return:
    lda $dd0d
restore_a:
    lda #0
    rti
nmi_end:
}
.const NMI_BYTES = nmi_end-nmi_entry
.assert "NMI must fit in the allocated zero page", NMI_BYTES <= 128, true

.label buffer_a = $0200
.label buffer_b = $0300
.import source "data.asm"
