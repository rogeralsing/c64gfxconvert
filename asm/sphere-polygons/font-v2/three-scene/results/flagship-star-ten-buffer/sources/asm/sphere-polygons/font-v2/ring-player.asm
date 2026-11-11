// Exact character deltas, ten independent full-screen buffers in VIC bank 1.
// Copy the displayed screen into the next slot, then decode into that slot.
// One complete field is held before work starts; presentation waits for line 256.
BasicUpstart2(start)

.label source_ptr = $02
.label page_left = $04
.label script_cursor = $05
.label images_left = $06
.label literal_destination = $07
.label literal_length = $09
.label literal_pages = $0a
.label literal_value = page_left

.macro next_source_byte() {
    iny
    bne !same_source_page+
    inc source_ptr+1
!same_source_page:
}

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

* = $1000 "Ten-screen ring player"
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
    sta front_index
    sta back_index
    sta script_cursor
    jsr read_command
    lda next_frame
    sta frame_index
    lda #$48
    sta front_screen_hi
    sta back_screen_hi
    lda #$4b
    sta back_end_hi
    lda #$20
    sta expected_d018
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
    and #$fc
    ora #2
    sta $dd00
    ldx #0
!initialize:
    lda #1
    .for (var page=0; page<4; page++) { sta $d800+page*$100,x }
    lda #0
    .for (var page=0; page<40; page++) { sta $4800+page*$100,x }
    inx
    beq !initialized+
    jmp !initialize-
!initialized:
    lda expected_d018
    sta $d018
    lda #$08
    sta $d016
    jsr wait_boundary
    lda #$1b
    sta $d011
    jmp presented

// This checkpoint follows the hardware flip. Its current raster image still
// contains the previous field, so frame_done is the complete-image checkpoint.
presented:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    jsr advance_script
    bcc !continue+
    jmp stopped
!continue:
    jsr choose_next_buffer
copy_start:
    jsr copy_full_screen
copy_end:
    nop
render_start:
    ldx frame_index
    lda patch_pointer_low,x
    sta source_ptr
    lda patch_pointer_high,x
    sta source_ptr+1
    jsr decode_literal
render_end:
    jsr wait_boundary
// The old screen/pose remain selected at this checkpoint. At least its second
// complete field has just finished, including any extra fields due to overruns.
held_frame_done:
presentation_start:
flip_screen:
    ldx back_index
    lda screen_d018_table,x
    sta expected_d018
    sta $d018
    stx front_index
    lda back_screen_hi
    sta front_screen_hi
    lda next_frame
    sta frame_index
    jmp presented
stopped:
    jmp stopped

choose_next_buffer:
    ldx front_index
    inx
    cpx #10
    bcc !ready+
    ldx #0
!ready:
    stx back_index
    lda screen_hi_table,x
    sta back_screen_hi
    clc
    adc #3
    sta back_end_hi
    rts

// Self-modification affects only absolute address operands in this routine.
// All ten screens are page-aligned, so indexed loads never cross a page.
copy_full_screen:
    lda front_screen_hi
    sta copy_load0+2
    clc
    adc #1
    sta copy_load1+2
    adc #1
    sta copy_load2+2
    adc #1
    sta copy_load3+2
    lda back_screen_hi
    sta copy_store0+2
    clc
    adc #1
    sta copy_store1+2
    adc #1
    sta copy_store2+2
    adc #1
    sta copy_store3+2
    ldx #0
    jmp copy_loop
    .align $100
copy_loop:
copy_load0:  lda $4800,x
copy_store0: sta $4c00,x
copy_load1:  lda $4900,x
copy_store1: sta $4d00,x
copy_load2:  lda $4a00,x
copy_store2: sta $4e00,x
copy_load3:  lda $4b00,x
copy_store3: sta $4f00,x
    inx
copy_branch:
    bne copy_loop
    rts
.assert "Copy loop branch has no page penalty", (copy_loop >> 8) == ((copy_branch+2) >> 8), true

// PLAY1,start8,count8,totalPlays16LE. Zero totalPlays means forever.
// HOLD0 leaves the displayed image untouched.
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
    ldy source_ptr
    lda #0
    sta source_ptr
    sta literal_destination
    lda back_screen_hi
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
    cmp back_end_hi
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
front_index: .byte 0
back_index: .byte 0
front_screen_hi: .byte $48
back_screen_hi: .byte $48
back_end_hi: .byte $4b
expected_d018: .byte $20
segment_start: .byte 0
segment_count: .byte 0
plays_left: .word 0
next_frame: .byte 0
screen_hi_table: .fill 10, $48+i*4
screen_d018_table: .fill 10, $20+i*$10
patch_pointer_low:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2)
patch_pointer_high:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2+1)
playback_script:
    .fill scriptData.getSize(), scriptData.get(i)
player_code_end:
.assert "Code and frame pointers fit below $2000", player_code_end <= $2000, true

* = $4000 "Immutable locked charset in VIC bank 1"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Locked font fills one VIC charset", *-font, 2048

* = $8000 "Unchanged exact literal character deltas"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Movie stays below I/O", animation_end <= $d000, true
