// Resident replay of a captured SID register-trace passage.
// PCM nibbles go through the volume DAC at 3848.625 Hz on a 256-cycle CIA
// timer; every captured voice and filter register write is replayed at its
// captured sample index. No foreground decoding: the whole passage is
// resident, so the IRQ only outputs one nibble and drains due events.
.label SID=$d400
.label sample_cnt=$20
.label tick_error=$22
.label tick_samples=$24
.label pcm_ptr=$25
.label evt_ptr=$27
.label evt_left=$2a
.label nibble_phase=$2c
.label played_tick_count=$fa
.label underrun_counter=$fc

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
    lda #0
    ldx #$2c
!clear:
    sta $20,x
    dex
    bpl !clear-
    ldx #24
!sid_clear:
    sta SID,x
    dex
    bpl !sid_clear-
    lda #<pcm_data
    sta pcm_ptr
    lda #>pcm_data
    sta pcm_ptr+1
    lda #<evt_data
    sta evt_ptr
    lda #>evt_data
    sta evt_ptr+1
    // Hard replay budget: even a corrupted compare cannot walk past the
    // emitted packet count.
    lda #<EVENT_COUNT
    sta evt_left
    lda #>EVENT_COUNT
    sta evt_left+1
    lda #0
    sta nibble_phase
    sta underrun_counter
    sta underrun_counter+1
    lda #200
    sta tick_error
    lda #0
    sta tick_error+1
    jsr prepare_tick_length
    jsr prepare_tick_length
    lda #<irq
    sta $fffe
    lda #>irq
    sta $ffff
    lda #SAMPLE_LATCH
    sta $dc04
    lda #0
    sta $dc05
    lda #$81
    sta $dc0d
    lda #$11
    sta $dc0e
    cli
!wait:
    jmp !wait-

prepare_tick_length:
    clc
    lda tick_error
    adc #ERR_ADD_LO
    sta tick_error
    lda tick_error+1
    adc #ERR_ADD_HI
    sta tick_error+1
    cmp #THRESH_HI
    bcc !short+
    bne !long+
    lda tick_error
    cmp #THRESH_LO
    bcc !short+
!long:
    sec
    lda tick_error
    sbc #THRESH_LO
    sta tick_error
    lda tick_error+1
    sbc #THRESH_HI
    sta tick_error+1
    lda #LONG_INTERVAL
    sta tick_samples
    rts
!short:
    lda #SHORT_INTERVAL
    sta tick_samples
    rts

irq:
    pha
    lda $dc0d
    // One PCM nibble out first: the DAC keeps its cadence even on busy ticks.
    ldy #0
    lda nibble_phase
    bne !low+
    lda (pcm_ptr),y
    lsr
    lsr
    lsr
    lsr
    jmp !out+
!low:
    lda (pcm_ptr),y
    and #$0f
!out:
    ora #D418_MODE
    sta SID+24
    lda nibble_phase
    eor #$01
    sta nibble_phase
    bne !same+
    inc pcm_ptr
    bne !same+
    inc pcm_ptr+1
!same:
    // Replay every captured register event due at or before this sample.
    // The event counter is a hard stop: even a corrupted compare cannot
    // replay more than the emitted packet count.
!evt:
    lda evt_left
    bne !armed+
    lda evt_left+1
    beq !evtout+
    lda evt_left
!armed:
    ldy #1
    lda (evt_ptr),y
    cmp sample_cnt+1
    bcc !play+
    bne !evtout+
    dey
    lda (evt_ptr),y
    cmp sample_cnt
    bcc !play+
    bne !evtout+
!play:
    lda evt_left
    sec
    sbc #1
    sta evt_left
    bcs !cnt+
    dec evt_left+1
!cnt:
    ldy #2
    lda (evt_ptr),y
    sta evt_write+1
    iny
    lda (evt_ptr),y
evt_write:
    sta SID
    lda evt_ptr
    clc
    adc #4
    sta evt_ptr
    bcc !evt-
    inc evt_ptr+1
    jmp !evt-
!evtout:
    inc sample_cnt
    bne !sched+
    inc sample_cnt+1
!sched:
    dec tick_samples
    bne !done_check+
    jsr prepare_tick_length
    inc played_tick_count
    bne !done_check+
    inc played_tick_count+1
!done_check:
    lda sample_cnt
    cmp #<pcm_end_ticks
    lda sample_cnt+1
    sbc #>pcm_end_ticks
    bcc !irqout+
    jmp done
!irqout:
    pla
    rti

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
