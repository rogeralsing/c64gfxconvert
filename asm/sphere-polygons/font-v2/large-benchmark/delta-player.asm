// Fixed-font character-delta benchmark. The build wrapper selects either a
// sparse-page or packets64 decoder and a direct or hidden-screen destination.
BasicUpstart2(start)

.label source_ptr = $02
.label next_source_ptr = $04
.label destination_ptr = $06
.label page_left = $08
.label packet_left = $09
.label packet_tag = $0a
.label packet_value = $0b
.var destination = HIDDEN_SCREEN ? $0800 : $0400

* = $1000 "Large-ball character-delta benchmark"
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
        sta $0400+page*$100,x
        .if (HIDDEN_SCREEN) { sta $0800+page*$100,x }
    }
    inx
    bne !initialize-
    ldx #0
!initial_tail:
    lda initial_screen+$300,x
    sta $0700,x
    .if (HIDDEN_SCREEN) { sta $0b00,x }
    inx
    cpx #232
    bne !initial_tail-
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    jsr wait_boundary
    lda #$1b
    sta $d011
    jmp report_after_scan

render_start:
    ldx frame_index
    lda patch_pointer_low,x
    sta source_ptr
    lda patch_pointer_high,x
    sta source_ptr+1
    inx
    lda patch_pointer_low,x
    sta next_source_ptr
    lda patch_pointer_high,x
    sta next_source_ptr+1
    .if (SPARSE_CODEC) {
        jsr decode_sparse
    } else {
        lda #<destination
        sta destination_ptr
        lda #>destination
        sta destination_ptr+1
        jsr decode_packets
    }
render_end:
    .if (HIDDEN_SCREEN) { jsr wait_boundary } else { nop }
copy_start:
    .if (HIDDEN_SCREEN) { jsr copy_hidden_to_front } else { nop }
copy_end:
    inc frame_index
report_after_scan:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    lda frame_index
    cmp #PREVIEW_FRAME_COUNT-1
    beq stopped
    jmp render_start
stopped:
    // A benchmark prefix stops on its last real pose. No discontinuous loop.
    jmp stopped

decode_sparse:
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
        sta destination+page*$100,x
        iny
        bne !value_read+
        inc source_ptr+1
    !value_read:
        dec page_left
        bne !pair-
    !page_done:
    }
    rts

decode_packets:
!packet:
    jsr read_source
    sta packet_tag
    and #63
    clc
    adc #1
    sta packet_left
    lda packet_tag
    and #192
    beq !advance+
    cmp #64
    beq !literal+
    cmp #128
    beq !repeat+
    jmp invalid_movie
!literal:
    ldy #0
!literal_copy:
    lda (source_ptr),y
literal_store:
    sta (destination_ptr),y
    iny
    cpy packet_left
    bne !literal_copy-
    clc
    lda source_ptr
    adc packet_left
    sta source_ptr
    bcc !advance+
    inc source_ptr+1
    jmp !advance+
!repeat:
    jsr read_source
    ldy #0
!repeat_copy:
repeat_store:
    sta (destination_ptr),y
    iny
    cpy packet_left
    bne !repeat_copy-
!advance:
    clc
    lda destination_ptr
    adc packet_left
    sta destination_ptr
    bcc !same_page+
    inc destination_ptr+1
!same_page:
    lda source_ptr
    cmp next_source_ptr
    bne !packet-
    lda source_ptr+1
    cmp next_source_ptr+1
    bne !packet-
    rts

read_source:
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !done+
    inc source_ptr+1
!done:
    rts

// Strictly ascending writes let the copy begin in the lower border and finish
// ahead of the next visible character fetches. PAL scanout proves the deadline.
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
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte HIDDEN_SCREEN ? 8 : 4
patch_pointer_low:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2)
patch_pointer_high:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2+1)
player_code_end:
.assert "Code and all frame pointers fit below font", player_code_end <= $2000, true

* = $2000 "Immutable 256-character average font"
font:
    .fill fontData.getSize(), fontData.get(i)
.assert "Font bytes", *-font, 2048

* = $2800 "Exact initial character screen"
initial_screen:
    .fill initialData.getSize(), initialData.get(i)
.assert "Initial screen bytes", *-initial_screen, 1000

* = $3000 "Character change stream"
animation:
    .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Movie stays below I/O", animation_end <= $d000, true
