.label c3_fraction = $14
.label c3_position_low = $15
.label c3_position_high = $16
.label c3_block_count = $17
.label c3_remaining = $18
.label c3_active = $19
.label c3_chunk = $1c
.label c3_done = $1d
.label c3_score_ptr = $1e
.label sid2_high_buffer = $0600
// Linus-style native software triangle plus reusable fixed-rate sample mixer.
// Bounded native music: SID3 bass/drums plus original C3 samples on SID2.
// The sample-and-hold NMI retains the frozen 126-cycle clock and preparation.
.label phase_low = $02
.label phase_reset = $03
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
    // The native mixer lives below the unchanged zero-page sample interrupt.
    ldx #0
!copy_mix:
    lda mix_image,x
    sta $20,x
    inx
    cpx #(mix_end-mix_samples)
    bne !copy_mix-
    ldx #0
!copy_sid2:
    lda sid2_image,x
    sta $0400,x
    lda sid2_pending_image,x
    sta $0500,x
    inx
    bne !copy_sid2-
    lda #$40
    sta $dd0c
    ldx #0
!copy_c3:
    lda c3_producer_image,x
    sta c3_produce_block,x
    inx
    cpx #(c3_producer_end-c3_produce_block)
    bne !copy_c3-
    jsr c3_initialize
!prefill:
    jsr c3_pump
    lda c3_fast_write+1
    cmp #241
    bcc !prefill-
    // Startup calibration precedes all audible SID initialization.
    jsr startup_audio_delay
    // The sample latch preserves A and P, leaving foreground X/Y untouched.
    ldx #0
!copy_nmi:
    lda nmi_image,x
    sta $80,x
    inx
    cpx #(nmi_end-nmi_common)
    bne !copy_nmi-
    lda #<nmi_entry
    sta $fffa
    lda #>nmi_entry
    sta $fffb
    lda #$4c
    sta $dc04
    // Keep both ordinary envelopes quiet before enabling their waveforms.
    // TEST plus triangle establishes a known zero oscillator level at rest;
    // gate remains set across note changes, avoiding full-strength attacks.
    lda #0
    sta $d405
    sta $d40c
sid1_sustain_load:
    lda #(SID1_SUSTAIN << 4)
    sta $d406
sid2_sustain_load:
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
sid3_sustain_load:
    lda #(SID3_SUSTAIN << 4)
    sta $d414
    lda #1
    sta $d412
master_output_load:
    lda #SID_OUTPUT_MODE
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
    // Prime the neutral held SID2 voltage before the shared envelope warmup.
    lda #54
    sta $d408
    lda #$09
    sta $d40b
sid2_release_load_0:
    lda #SID2_RELEASE_CONTROL
    sta $d40b
    .fill 119, $ea
sid2_latch_load_0:
    lda #SID2_LATCH_CONTROL
    sta $d40b
    lda #$09
    sta $d40b
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
    jsr startup_initial_delay
    lda pending_start_low
    sta buffer_read+1
    lda #>buffer_a
    sta buffer_read+2
    lda #54
    sta $d408
    jsr commit_sid
    bit $ea
    .fill 8, $ea
sid2_release_load_1:
    lda #SID2_RELEASE_CONTROL
sid2_startup_release:
    sta $d40b
    bit $ea
    .fill 3, $ea

    // CIA1 TA remains stopped: its counter bytes are the JMP opcode/low byte.
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
    sta destination+2
    jsr fill_frame
    lda boundary_count
    cmp boundary_before
    beq !prepared+
    inc underruns
!prepared:
background_begin:
    lda c3_done
    bne background_done
    lda c3_fast_write+1
    sec
    sbc sid2_read_high+1
    cmp #209
    bcs background_done
background_chunk:
    lda boundary_count
    cmp boundary_before
    bne background_done
    jsr c3_pump
    lda c3_remaining
    bne background_chunk
    jmp background_begin
background_done:
wait_start:
    lda boundary_count
    cmp boundary_before
    beq wait_start
!sid1_committed:
    lda sid2_dispatch+2
    cmp #>sid2_phase0
    bne !sid1_committed-
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
    ldy #0
    lda (score_ptr),y
    sta rle_end_read+1
    sta rle_value_read+1
    sta phase_low
    iny
    lda (score_ptr),y
    sta rle_end_read+2
    sta rle_value_read+2
    sta phase_reset
    iny
    lda (score_ptr),y
    sta sample_read+1
    iny
    lda (score_ptr),y
    sta sample_read+2
    iny
    lda (score_ptr),y
    sta pending_start_low
    sta destination+1
    eor #$ff
    clc
    adc #1
    sta rle_frame_end+1
    ldy #6
    lda (score_ptr),y
    sta pending_sid
    iny
    lda (score_ptr),y
    sta pending_sid+1
    iny
    lda (score_ptr),y
    sta pending_sid+2
    clc
    lda score_ptr
    adc #12
    sta score_ptr
    bcc !score_ready+
    inc score_ptr+1
!score_ready:
    ldx #0
    ldy #0
    // The first run ending at frame length proves the whole frame constant.
    lda (phase_low),y
    cmp rle_frame_end+1
    bne !regular+
    iny
    lda (phase_low),y
    tax
    ldy #0
    // Patch the unrolled operands only when this fast path will run.
    lda sample_read+2
    sta constant_sample0+2
    sta constant_sample1+2
    sta constant_sample2+2
    sta constant_sample3+2
    sta constant_sample4+2
    lda sample_read+1
    sta constant_sample0+1
    sta constant_sample1+1
    sta constant_sample2+1
    sta constant_sample3+1
    sta constant_sample4+1
    lda pending_start_low
    sta constant_destination0+1
    sta constant_destination1+1
    sta constant_destination2+1
    sta constant_destination3+1
    sta constant_destination4+1
    lda rle_frame_end+1
    sta constant_end+1
    lda destination+2
    sta constant_destination0+2
    sta constant_destination1+2
    sta constant_destination2+2
    sta constant_destination3+2
    sta constant_destination4+2
    jsr mix_constant
    jmp !mixed+
!regular:
    clc
    jsr mix_samples
!mixed:
    inc generated_frames
    bne !counted+
    inc generated_frames+1
!counted:
fill_end:
fill_frame_rts:
    rts

// Reusable triangle run programs, mixed with the independent sample lane.
// Y starts at zero. Both source/destination low operands hold 256-count, so
// their indexed accesses stay in one page. Commands are (endY, bassCode).
// Each command list stays within one page, keeping both absolute-X reads at
// four cycles. CPY leaves carry clear while a run/frame still has samples.
mix_image:
.pseudopc $20 {
mix_samples:
rle_next_run:
rle_end_read:
    lda $ffff,x
    sta rle_run_end+1
    inx
rle_value_read:
    lda $ffff,x
    sta rle_bass_value+1
    inx
rle_run:
rle_bass_value:
    lda #15
sample_read:
    adc silence_page,y
destination:
    sta buffer_b,y
    iny
rle_run_end:
    cpy #156
    bne rle_run
rle_frame_end:
    cpy #156
    beq rle_done
    jmp rle_next_run
rle_done:
    rts
mix_primary_end:

// A complete constant-level frame has no run transitions. Emit four samples
// per branch, using the same independent drum page. X holds the bass level.
// The optional first value handles 157 samples; 156 is exactly 39 groups.
mix_constant:
    lda rle_frame_end+1
    lsr
    bcc constant_group
    clc
    txa
constant_sample0:
    adc silence_page,y
constant_destination0:
    sta buffer_b,y
    iny
constant_group:
    txa
constant_sample1:
    adc silence_page,y
constant_destination1:
    sta buffer_b,y
    iny
    txa
constant_sample2:
    adc silence_page,y
constant_destination2:
    sta buffer_b,y
    iny
    txa
constant_sample3:
    adc silence_page,y
constant_destination3:
    sta buffer_b,y
    iny
    txa
constant_sample4:
    adc silence_page,y
constant_destination4:
    sta buffer_b,y
    iny
constant_end:
    cpy #156
    bne constant_group
    rts
mix_end:
}
.assert "RLE mixer must stay below the sample interrupt", mix_end <= $80, true

commit_sid:
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
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

sid2_image:
.pseudopc $0400 {
sid2_phase0:
sid2_latch_load_1:
    lda #SID2_LATCH_CONTROL
    sta $d40b
    lda #$09
    sta $d40b
    lda #<sid2_phase1
    .byte $85, <(sid2_dispatch+1)
    jmp sid2_finished
    .fill $0440-*, $ea
sid2_phase1:
    // Only a phase1 boundary can make the next phase2 a pending SID1 commit.
    // Keep one authoritative cursor; copy its value at that rare boundary.
    inc sid2_read_high+1
    lda #<sid2_phase2
    .byte $85, <(sid2_dispatch+1)
    .byte $e6, <(buffer_read+1)
    beq !boundary+
    .byte $a5, <(restore_a+1)
    jmp $dd0c
!boundary:
    lda sid2_read_high+1
    sta sid2_pending_read_high+1
    jmp frame_boundary
    .fill $0480-*, $ea
sid2_phase2:
sid2_read_high:
    lda sid2_high_buffer
    sta $d408
sid2_release_load_2:
    lda #SID2_RELEASE_CONTROL
    sta $d40b
    lda #<sid2_phase3
    .byte $85, <(sid2_dispatch+1)
    jmp sid2_finished
    .fill $04c0-*, $ea
sid2_phase3:
    lda #<sid2_phase0
    .byte $85, <(sid2_dispatch+1)
    jmp sid2_finished
    .fill $0500-*, $ea
}

sid2_pending_image:
.pseudopc $0500 {
sid2_pending_phase0:
sid2_latch_load_2:
    lda #SID2_LATCH_CONTROL
    sta $d40b
    lda #$09
    sta $d40b
    bit $ea
    .fill 1, $ea
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda #<sid2_phase1
    .byte $85, <(sid2_dispatch+1)
    lda #>sid2_phase0
    .byte $85, <(sid2_dispatch+2)
    .byte $e6, <(buffer_read+1)
    jmp nmi_return
    .fill $0540-*, $ea
sid2_pending_phase1:
    inc sid2_read_high+1
    bit $ea
    .fill 4, $ea
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda #<sid2_phase2
    .byte $85, <(sid2_dispatch+1)
    lda #>sid2_phase0
    .byte $85, <(sid2_dispatch+2)
    .byte $e6, <(buffer_read+1)
    jmp nmi_return
    .fill $0580-*, $ea
sid2_pending_phase2:
sid2_pending_read_high:
    lda sid2_high_buffer
    sta $d408
sid2_release_load_3:
    lda #SID2_RELEASE_CONTROL
    sta $d40b
    bit $ea
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda #<sid2_phase3
    .byte $85, <(sid2_dispatch+1)
    lda #>sid2_phase0
    .byte $85, <(sid2_dispatch+2)
    .byte $e6, <(buffer_read+1)
    jmp nmi_return
    .fill $05c0-*, $ea
sid2_pending_phase3:
    bit $ea
    .fill 7, $ea
    lda pending_sid
    sta $d400
    lda pending_sid+1
    sta $d401
    lda pending_sid+2
    sta $d404
    lda #<sid2_phase0
    .byte $85, <(sid2_dispatch+1)
    lda #>sid2_phase0
    .byte $85, <(sid2_dispatch+2)
    .byte $e6, <(buffer_read+1)
    jmp nmi_return
    .fill $0600-*, $ea
}

.align $100
nmi_image:
.pseudopc $80 {
nmi_common:
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
sid2_dispatch:
    jmp sid2_phase0
sid2_finished:
    .byte $e6, <(buffer_read+1)
    bne nmi_return
frame_boundary:
    inc boundary_count
    .byte $e6, <(sid2_dispatch+2)
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
pointer_commit:
nmi_return:
restore_a:
    lda #0
    jmp $dd0c
.label nmi_rti = $dd0c
nmi_end:
}
.const NMI_BYTES = nmi_end-nmi_common
.assert "NMI must fit in the allocated zero page", NMI_BYTES <= 128, true

runtime_end:

.label buffer_a = $0200
.label buffer_b = $0300
.label nmi_entry = $dc04
.import source "data.asm"

// CIA1 TB supplies the page; a higher count denotes earlier entry.
.for (var page = $70; page <= $78; page++) {
    .pc = page * $100 "Distributed jitter entry"
    .var delta = page-$70
    .fill floor(delta/2), $ea
    .if (mod(delta,2) == 0) {
        .byte $85, <(restore_a+1)
    } else {
        .byte $8d, <(restore_a+1), >(restore_a+1)
    }
    jmp nmi_common
}


.pc = $c000 "C3 bounded foreground producer"
c3_initialize:
    lda #255
    sta c3_fraction
    lda #0
    sta c3_position_low
    sta c3_position_high
    sta c3_remaining
    sta c3_active
    sta c3_done
    lda #<score
    sta c3_score_ptr
    lda #>score
    sta c3_score_ptr+1
    lda #<FRAME_COUNT
    sta c3_frames_left
    lda #>FRAME_COUNT
    sta c3_frames_left+1
    rts

// Dispatch directly to the current source segment. Only its one remaining
// counter changes per block; a prepared active prefix is followed by its tail.
c3_pump:
    jmp c3_next_segment
c3_active_block:
    lda c3_remaining
    bne !active+
    jmp c3_next_segment
!active:
    cmp #16
    bcc !short+
    sbc #16
    sta c3_remaining
    lda #16
    sta c3_block_count
c3_active_emit:
    lda c3_position_low
    cmp #240
    bcs !boundary+
    jsr c3_produce_fast_block
    rts
!boundary:
    lda c3_fast_write+1
    sta c3_write+1
    jsr c3_produce_block
    lda c3_write+1
    sta c3_fast_write+1
    lda c3_read+2
    sta c3_fast_read+2
    rts
!short:
    sta c3_block_count
    lda #0
    sta c3_remaining
    jmp c3_active_emit
c3_ended_block:
    lda c3_remaining
    bne !ended+
    jmp c3_next_segment
!ended:
    cmp #16
    bcc !smaller+
    sbc #16
    sta c3_remaining
    jsr c3_emit_ended_full8
    jsr c3_emit_ended_full8
    rts
!smaller:
    cmp #8
    bcc !short+
    sbc #8
    sta c3_remaining
    jsr c3_emit_ended_full8
    rts
!short:
    sta c3_block_count
    lda #0
    sta c3_remaining
    jsr c3_emit_ended_block
    rts
c3_next_segment:
    lda c3_active
    beq c3_open_frame
    sta c3_remaining
    lda #0
    sta c3_active
    lda #<c3_ended_block
    sta c3_pump+1
    lda #>c3_ended_block
    sta c3_pump+2
    rts
c3_open_frame:
    lda c3_done
    beq !pending+
    rts
!pending:
    lda c3_frames_left
    ora c3_frames_left+1
    bne !open+
    inc c3_done
    rts
!open:
    lda c3_frames_left
    bne !count+
    dec c3_frames_left+1
!count:
    dec c3_frames_left
    ldy #11
    lda (c3_score_ptr),y
    sta c3_remaining
    ldy #5
    lda (c3_score_ptr),y
    sec
    sbc c3_remaining
    sta c3_active
    lda c3_remaining
    beq !ended+
    lda #<c3_active_block
    sta c3_pump+1
    lda #>c3_active_block
    sta c3_pump+2
    jmp !mode+
!ended:
    lda c3_active
    sta c3_remaining
    lda #0
    sta c3_active
    lda #<c3_ended_block
    sta c3_pump+1
    lda #>c3_ended_block
    sta c3_pump+2
!mode:
    ldy #9
    lda (c3_score_ptr),y
    sta c3_step+1
    sta c3_fast_step+1
    iny
    lda (c3_score_ptr),y
    bpl !hold+
    ldx #255
    stx c3_fraction
    ldx #0
    stx c3_position_low
    stx c3_position_high
!hold:
    and #127
    tax
    cpx #C3_SILENT_VARIANT
    beq !muted+
    lda #$b9
    sta c3_read
    sta c3_fast_read
    lda c3_bank_low,x
    sta c3_read+1
    sta c3_fast_read+1
    lda c3_bank_high,x
    clc
    adc c3_position_high
    sta c3_read+2
    sta c3_fast_read+2
    lda #$e6
    sta c3_read_high_advance
    jmp !ready+
!muted:
    lda #$ad
    sta c3_read
    sta c3_fast_read
    lda #<c3_neutral
    sta c3_read+1
    sta c3_fast_read+1
    lda #>c3_neutral
    sta c3_read+2
    sta c3_fast_read+2
    lda #$24
    sta c3_read_high_advance
!ready:
    clc
    lda c3_score_ptr
    adc #12
    sta c3_score_ptr
    bcc !pointer+
    inc c3_score_ptr+1
!pointer:
    rts
c3_neutral:
    .byte 54
c3_frames_left:
    .word 0

// Bounded native direct-frequency producer. Caller supplies these ZP labels:
// c3_fraction (255-phaseLow), c3_position_low/high and c3_block_count (1..16).
// Before a block, patch c3_step+1 and c3_read to virtualBase+positionHigh,Y.
// Active audible mode: read opcode=$b9, c3_read_high_advance opcode=$e6.
// Muted mode: read opcode=$ad at a constant neutral byte, advance opcode=$24
// (BIT zp). Muted active sources still advance; ended tails use step zero.
// No per-output end test exists: caller must stop each active prefix exactly
// at its prepared lifetime bound. The first20s proof never reaches a loop.
// Ring write starts at1: index0 represents the separately primed neutral latch.
c3_producer_image:
.pseudopc $c0 {
c3_produce_block:
    ldx c3_fraction
    ldy c3_position_low
c3_produce_loop:
c3_read:
    lda $ffff,y
c3_ring_store:
c3_ring_store_slow:
c3_write:
    sta $0601
    inc c3_write+1
    txa
c3_step:
    .byte $cb, $00             // SBX: descending fractional phase in X.
    bcs c3_advanced
    iny
    bne c3_advanced
    inc c3_position_high
c3_read_high_advance:
    inc c3_read+2
c3_advanced:
    dec c3_block_count
    bne c3_produce_loop
    stx c3_fraction
    sty c3_position_low
c3_produce_block_rts:
    rts
c3_primary_end:

// Fast entry additionally requires positionLow<256-blockLimit: below248 for
// eight-value blocks, below240 for sixteen. These bounded unit advances cannot
// wrap Y, so neither source-high update is needed inside.
// Keep this write pointer canonical; only slow boundary blocks need to copy
// its low byte to/from c3_write+1. Mirror read/step patches when frames change.
c3_produce_fast_block:
    ldx c3_fraction
    ldy c3_position_low
c3_fast_loop:
c3_fast_read:
    lda $ffff,y
c3_ring_store_fast:
c3_fast_write:
    sta $0601
    inc c3_fast_write+1
    txa
c3_fast_step:
    .byte $cb, $00
    bcs c3_fast_advanced
    iny
c3_fast_advanced:
    dec c3_block_count
    bne c3_fast_loop
    stx c3_fraction
    sty c3_position_low
c3_fast_block_rts:
    rts
c3_producer_end:
}
.assert "C3 producer must fit above the unchanged sample ISR", c3_producer_end <= $100, true

// Ended sources have no advancing cursor. This caller-side kernel is ordinary
// RAM code; X indexes the ring directly. Never use it for a muted active note.
c3_emit_ended_block:
    ldx c3_fast_write+1
c3_neutral_load:
    lda #54
!ended_loop:
c3_ring_store_ended:
    sta $0600,x
    inx
    dec c3_block_count
    bne !ended_loop-
    stx c3_fast_write+1
    stx c3_write+1
c3_ended_block_rts:
    rts

// Common eight-value ended block: no per-value counter/branch is necessary.
// Short tails retain c3_emit_ended_block above. Both paths leave count zero.
c3_emit_ended_full8:
    ldx c3_fast_write+1
c3_full8_neutral_load:
    lda #54
c3_ring_store_ended_0:
    sta $0600,x
    inx
c3_ring_store_ended_1:
    sta $0600,x
    inx
c3_ring_store_ended_2:
    sta $0600,x
    inx
c3_ring_store_ended_3:
    sta $0600,x
    inx
c3_ring_store_ended_4:
    sta $0600,x
    inx
c3_ring_store_ended_5:
    sta $0600,x
    inx
c3_ring_store_ended_6:
    sta $0600,x
    inx
c3_ring_store_ended_7:
    sta $0600,x
    inx
    stx c3_fast_write+1
    stx c3_write+1
    lda #0
    sta c3_block_count
c3_ended_full8_rts:
    rts

.assert "C3 management code must leave delay routines free", * <= $c300, true

.pc = $c300 "Stable startup delay"
startup_audio_delay:
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #255
!rle_delay:
    dex
    bne !rle_delay-
    ldx #208
!rle_delay:
    dex
    bne !rle_delay-
    rts
.assert "Startup delay must remain in one code page", * < $c400, true

.pc = $c400 "Stable initial-note delay"
startup_initial_delay:
    ldx #252
!rle_delay:
    dex
    bne !rle_delay-
    nop
    nop
    nop
    rts
.assert "Initial delay must remain in one code page", * < $c500, true

.assert "Bootstrap must not overlap resident instruments", runtime_end <= $1000, true
