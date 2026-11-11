// Replay sparse SID register frames with a fixed PAL CIA timer.
.label SID = $d400
.label stream_ptr = $20
.label playlist_ptr = $22
.label hold_frames = $24
.label frame_due = $25
.label played_frame_count = $26
.label underrun_counter = $28
.label write_count = $2a

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
    ldx #$0a
!clear:
    sta $20,x
    dex
    bpl !clear-
    ldx #24
!sid_clear:
    sta SID,x
    dex
    bpl !sid_clear-
    lda #<irq
    sta $fffe
    lda #>irq
    sta $ffff
    lda #<song_playlist
    sta playlist_ptr
    lda #>song_playlist
    sta playlist_ptr+1
    jsr next_block
    lda #<(FRAME_CYCLES-1)
    sta $dc04
    lda #>(FRAME_CYCLES-1)
    sta $dc05
    lda #$81
    sta $dc0d
    // Start the timer before decoding frame0, preserving the frame phase.
    // The first volume=15 bus write anchors frame0 in captured audio.
song_started:
    lda #15
    sta SID+24
    lda #$11
    sta $dc0e
    cli
    jsr play_frame
!wait:
    lda frame_due
    beq !wait-
    dec frame_due
    jsr play_frame
    jmp !wait-

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
!halt:
    jmp !halt-

get_byte:
    ldy #0
    lda (stream_ptr),y
    inc stream_ptr
    bne !ready+
    inc stream_ptr+1
!ready:
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

play_frame:
    lda hold_frames
    beq !command+
    dec hold_frames
    jmp !counted+
!command:
    jsr get_byte
    bne !not_end+
    jsr next_block
    jmp !command-
!not_end:
    bmi !hold+
    sta write_count
    ldy #0
!write:
    lda (stream_ptr),y
    tax
    iny
    lda (stream_ptr),y
    sta SID,x
    iny
    dec write_count
    bne !write-
    tya
    clc
    adc stream_ptr
    sta stream_ptr
    bcc !counted+
    inc stream_ptr+1
    jmp !counted+
!hold:
    and #$7f
    sec
    sbc #1
    sta hold_frames
!counted:
    inc played_frame_count
    bne !return+
    inc played_frame_count+1
!return:
    rts

irq:
    pha
    lda $dc0d
    inc frame_due
    lda frame_due
    cmp #2
    bcc !ready+
    inc underrun_counter
    bne !ready+
    inc underrun_counter+1
!ready:
    pla
    rti
player_end:
