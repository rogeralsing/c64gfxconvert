// Exact scene. Two PAL fields per image; optionally repeat a suffix forever.
// The first image is an implicit blank screen cleared during startup.
BasicUpstart2(start)

.label source_ptr = $02
.label page_left = $04
.label script_cursor = $05
.label images_left = $06

.macro next_source_byte() {
    iny
    bne !same_source_page+
    inc source_ptr+1
!same_source_page:
}

* = $1000 "Finite scripted character scene"
start:
    sei
    cld
    lda #$2f
    sta $00
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    sta $d020
    sta $d021
    sta frame_index
    sta frame_counter
    sta frame_counter+1
    sta script_cursor
    jsr read_command
    lda next_frame
    sta frame_index
    lda #$0b
    sta $d011
    lda #$0f
    sta $d019
    lda #<interrupt_return
    sta $fffa
    sta $fffe
    lda #>interrupt_return
    sta $fffb
    sta $ffff
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    ldx #0
!initialize:
    lda #1
    .for (var page=0; page<4; page++) { sta $d800+page*$100,x }
    lda #0
    .for (var page=0; page<4; page++) { sta $0400+page*$100,x }
    inx
    bne !initialize-
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    jsr wait_boundary
    lda #$1b
    sta $d011
presentation_start:
    jmp report_after_scan

render_start:
    ldx frame_index
    lda patch_pointer_low,x
    sta source_ptr
    lda patch_pointer_high,x
    sta source_ptr+1
    jsr decode_sparse
render_end:
    nop
copy_start:
    nop
copy_end:
    lda next_frame
    sta frame_index
report_after_scan:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // Keep each image for one additional complete field.
    jsr wait_boundary
held_frame_done:
    jsr advance_script
    bcs stopped
    jmp render_start
stopped:
    jmp stopped

// PLAY1,start8,count8,totalPlays16LE. Zero totalPlays means forever.
// HOLD0 leaves the last displayed image untouched.
read_command:
    ldy script_cursor
    lda playback_script,y
    beq !hold+
    lda playback_script+1,y
    sta segment_start
    sta next_frame
    lda playback_script+2,y
    sta segment_count
    sta images_left
    lda playback_script+3,y
    sta plays_left
    lda playback_script+4,y
    sta plays_left+1
    tya
    clc
    adc #5
    sta script_cursor
    clc
    rts
!hold:
    sec
    rts

advance_script:
    dec images_left
    bne !within_segment+
    lda plays_left
    ora plays_left+1
    beq !repeat_segment+
    lda plays_left+1
    bne !decrement_repeat+
    lda plays_left
    cmp #1
    beq read_command
!decrement_repeat:
    lda plays_left
    bne !low_nonzero+
    dec plays_left+1
!low_nonzero:
    dec plays_left
!repeat_segment:
    lda segment_count
    sta images_left
    lda segment_start
    sta next_frame
    clc
    rts
!within_segment:
    lda frame_index
    clc
    adc #1
    sta next_frame
    clc
    rts

// Existing four-page sparse codec: count followed by offset/glyph pairs.
decode_sparse:
    ldy #0
    .for (var page=0; page<4; page++) {
        lda (source_ptr),y
        sta page_left
        :next_source_byte()
        lda page_left
        beq !page_done+
    !pair:
        lda (source_ptr),y
        tax
        :next_source_byte()
        lda (source_ptr),y
        sta $0400+page*$100,x
        :next_source_byte()
        dec page_left
        bne !pair-
    !page_done:
    }
    rts

wait_boundary:
!leave_high:
    bit $d011
    bmi !leave_high-
!enter_high:
    bit $d011
    bpl !enter_high-
    rts
interrupt_return:
    rti

frame_index: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 4
segment_start: .byte 0
segment_count: .byte 0
plays_left: .word 0
next_frame: .byte 0
patch_pointer_low:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2)
patch_pointer_high:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2+1)
playback_script:
    .fill scriptData.getSize(), scriptData.get(i)
player_code_end:
.assert "Code and frame pointers fit below font", player_code_end <= $2000, true

* = $2000 "Immutable coarse average font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Font bytes", *-font, 1344

* = $3000 "Finite sparse-page character changes"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Movie stays below I/O", animation_end <= $d000, true
