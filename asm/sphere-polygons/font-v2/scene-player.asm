// Exact scene. Two PAL fields per image; optionally repeat a suffix forever.
// The first image is an implicit blank screen cleared during startup.
BasicUpstart2(start)

.if (MOVIE_POOLED) {
    .assert "BASIC ends below low movie pool", * <= $0900, true
    * = $0900 "Sparse patches in low RAM gap"
    movie_low: .fill movieLowData.getSize(), movieLowData.get(i)
    .assert "Low movie pool ends below code", * <= $1000, true
}

.label source_ptr = $02
.label page_left = $04
.label script_cursor = $05
.label images_left = $06
.label literal_destination = $07
// The short-copy dispatch reuses length/pages as a two-byte jump pointer.
.label literal_length = $09
.label literal_pages = $0a
.label literal_value = page_left

.macro next_source_byte() {
    iny
    bne !same_source_page+
    inc source_ptr+1
!same_source_page:
}

// The host encoder emits at most two LEB128 bytes for skips and lengths.
// A is the low byte and X the high byte; Y remains the source page offset.
.macro literal_variable() {
    lda (source_ptr),y
    bpl !short+
    and #$7f
    sta literal_value
    :next_source_byte()
    lda (source_ptr),y
    lsr
    tax
    lda literal_value
    bcc !low_ready+
    ora #$80
!low_ready:
    :next_source_byte()
    jmp !ready+
!short:
    :next_source_byte()
    ldx #0
!ready:
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
    .if (LITERAL_CODEC) { jsr decode_literal } else { jsr decode_sparse }
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

decode_literal:
decode_sparse:
.if (!LITERAL_CODEC) {
// Existing four-page sparse codec: count followed by offset/glyph pairs.
    .if (MOVIE_POOLED) {
        // Keep (source_ptr),Y within one page to avoid indexed-read penalties.
        ldy source_ptr
        lda #0
        sta source_ptr
    } else {
        ldy #0
    }
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

} else {
    ldy source_ptr
    lda #0
    sta source_ptr
    sta literal_destination
    lda #4
    sta literal_destination+1
    lda #>!short_end+
    sta literal_pages
!pair:
    lda (source_ptr),y
    bmi !wide_skip+
    :next_source_byte()
    clc
    adc literal_destination
    sta literal_destination
    bcc !length+
    inc literal_destination+1
    jmp !length+
!wide_skip:
    :literal_variable()
    clc
    adc literal_destination
    sta literal_destination
    txa
    adc literal_destination+1
    sta literal_destination+1
!length:
    lda (source_ptr),y
    bmi !wide_length+
    :next_source_byte()
    tax
    cpx #33
    bcs !long_short+
    // Short literals dominate this stream. Jump into an unrolled copy suffix;
    // zero length jumps straight to completion. The pointer reuses length RAM.
    sty source_ptr
    ldy #0
    lda !short_low+,x
    sta literal_length
    jmp (literal_length)
!long_short:
    sta literal_length
    lda #0
    sta literal_pages
    jmp !general+
!wide_length:
    :literal_variable()
    sta literal_length
    stx literal_pages
!general:
    // Complete 256-byte copies advance both pointer pages. This path also
    // handles every legal two-byte skip/length, including a full 1,000-byte frame.
    sty source_ptr
    ldy #0
    lda literal_pages
    beq !tail+
!full_page:
    ldx #32
!full_eight:
    .for (var item=0; item<8; item++) {
        lda (source_ptr),y
        sta (literal_destination),y
        iny
    }
    dex
    bne !full_eight-
    inc source_ptr+1
    inc literal_destination+1
    dec literal_pages
    bne !full_page-
!tail:
    lda literal_length
    lsr
    lsr
    lsr
    tax
    beq !remainder+
!eight:
    .for (var item=0; item<8; item++) {
        lda (source_ptr),y
        sta (literal_destination),y
        iny
    }
    dex
    bne !eight-
!remainder:
    lda literal_length
    and #7
    tax
    beq !general_done+
!one:
    lda (source_ptr),y
    sta (literal_destination),y
    iny
    dex
    bne !one-
!general_done:
    lda #>!short_end+
    sta literal_pages
    jmp !copied+
    .align $100
!short_copy:
    .for (var item=0; item<32; item++) {
        lda (source_ptr),y
        sta (literal_destination),y
        iny
    }
!short_end:
!copied:
    tya
    clc
    adc literal_destination
    sta literal_destination
    bcc !destination_page+
    inc literal_destination+1
!destination_page:
    tya
    clc
    adc source_ptr
    tay
    bcc !source_page+
    inc source_ptr+1
!source_page:
    lda #0
    sta source_ptr
    lda literal_destination+1
    cmp #7
    beq !last_page+
    jmp !pair-
!last_page:
    lda literal_destination
    cmp #$e8
    beq !done+
    jmp !pair-
!done:
    rts
!short_low:
    .fill 33, <(!short_end- - i*5)
}

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

.if (MOVIE_POOLED) {
    .assert "Code and pointers end below middle movie pool", player_code_end <= MOVIE_MIDDLE_START, true
    * = MOVIE_MIDDLE_START "Character patches after code and pointers"
    movie_middle: .fill movieMiddleData.getSize(), movieMiddleData.get(i)
    .assert "Middle movie pool ends below font", * <= $2000, true
}

* = $2000 "Immutable coarse average font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Original font prefix present", *-font >= 1344, true
.assert "Font fits VIC charset", *-font <= 2048, true
.assert "Font has whole glyphs", (fontData.getSize() & 7), 0

.if (MOVIE_POOLED) {
    * = $2800 "Sparse patches after VIC font"
    movie_upper: .fill movieUpperData.getSize(), movieUpperData.get(i)
    .assert "Upper movie pool ends below main data", * <= $3000, true
}

* = $3000 "Finite sparse-page character changes"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Movie stays below I/O", animation_end <= $d000, true
