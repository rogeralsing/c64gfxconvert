// Exact font-v2 character playback. The hidden screen is a persistent mirror:
// apply a reversible XOR patch there, then copy it to the visible screen in
// ascending address order at lower-border line 256. No bitmap is rendered here.
BasicUpstart2(start)
.import source "build/player-config.inc"

.label source_ptr = $02
.label page_left = $04

* = $1000 "Bounded reversible character player"
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
    sta next_frame_index
    sta frame_counter
    sta frame_counter+1
    sta direction
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
    .for (var page=0; page<3; page++) {
        lda initial_screen+page*$100,x
        sta $0800+page*$100,x
    }
    inx
    bne !initialize-
    ldx #0
!initial_tail:
    lda initial_screen+$300,x
    sta $0b00,x
    inx
    cpx #232
    bne !initial_tail-
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    jsr copy_hidden_to_front
    jsr wait_boundary
    lda #$1b
    sta $d011
    jmp report_after_scan

render_start:
    jsr select_patch
    jsr decode_xor
render_end:
    // If hidden decoding fits one field, this boundary and the post-copy
    // boundary produce one new image every two PAL fields. Native verification
    // must establish this cadence and all front-copy row-fetch deadlines.
    jsr wait_boundary
copy_start:
    jsr copy_hidden_to_front
copy_end:
    lda next_frame_index
    sta frame_index
report_after_scan:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // frame_index identifies the image whose complete visible scan just ended.
    jmp render_start

select_patch:
    lda direction
    bne !backward+
    lda frame_index
    cmp #PREVIEW_FRAME_COUNT-1
    bne !forward+
    lda #1
    sta direction
!backward:
    lda frame_index
    beq !turn_forward+
    sec
    sbc #1
    sta next_frame_index
    tax
    jmp !pointer+
!turn_forward:
    lda #0
    sta direction
    lda frame_index
!forward:
    tax
    clc
    adc #1
    sta next_frame_index
!pointer:
    lda patch_pointer_low,x
    sta source_ptr
    lda patch_pointer_high,x
    sta source_ptr+1
    rts

// Four sparse page records: count8, then count (offset8, XOR-mask8) pairs.
// The source low byte stays fixed; Y wrapping advances the source high byte.
// Page-specific absolute addressing avoids indirect destination work per pair.
decode_xor:
    ldy #0
    .for (var page=0; page<4; page++) {
        lda (source_ptr),y
        sta page_left
        iny
        bne !count_read+
        inc source_ptr+1
    !count_read:
        lda page_left
        beq !page_done+
    !pair:
        lda (source_ptr),y
        tax
        iny
        bne !offset_read+
        inc source_ptr+1
    !offset_read:
        lda (source_ptr),y
        eor $0800+page*$100,x
        sta $0800+page*$100,x
        iny
        bne !mask_read+
        inc source_ptr+1
    !mask_read:
        dec page_left
        bne !pair-
    !page_done:
    }
    rts

// Four independent page loops retain strictly ascending destination stores.
// Unroll 32 bytes per iteration to reduce loop overhead while keeping code
// below the immutable font at $2000. The last page contains only 232 cells.
copy_hidden_to_front:
    .for (var page=0; page<3; page++) {
        ldx #0
    !page_loop:
        .for (var offset=0; offset<32; offset++) {
            lda $0800+page*$100+offset,x
            sta $0400+page*$100+offset,x
        }
        txa
        clc
        adc #32
        tax
        beq !page_done+
        jmp !page_loop-
    !page_done:
    }
    ldx #0
!tail_loop:
    .for (var offset=0; offset<8; offset++) {
        lda $0b00+offset,x
        sta $0700+offset,x
    }
    txa
    clc
    adc #8
    tax
    cpx #232
    bne !tail_loop-
    rts

wait_boundary:
!leave_high:
    bit $d011
    bmi !leave_high-
!enter_high:
    bit $d011
    bpl !enter_high-
    rts
invalid_movie:
    brk
    jmp invalid_movie
interrupt_return:
    rti

frame_index: .byte 0
next_frame_index: .byte 0
frame_counter: .word 0
direction: .byte 0
front_screen_hi: .byte 4
back_screen_hi: .byte 8
.import source "build/player-pointers.inc"
player_code_end:
.assert "Player code stays below font", player_code_end <= $2000, true

* = $2000 "Immutable 256-character average font"
font:
    .import binary "build/font.bin"
.assert "Font is 256 eight-byte glyphs", *-font, 2048

* = $2800 "Exact initial 40x25 character screen"
initial_screen:
    .import binary "build/player-initial.screen"
.assert "Initial screen bytes", *-initial_screen, 1000

* = $3000 "Reversible XOR transition records"
animation:
    .import binary "build/player-movie.xor"
animation_end:
.assert "Expected serialized source bytes", animation_end-animation, PREVIEW_SOURCE_BYTES
.assert "Movie remains below I/O", animation_end <= $d000, true
