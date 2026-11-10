// Fixed byte-Huffman decoder benchmark. First8 bits select a symbol or a
// secondary2-bit lookup; alignment tables avoid per-bit tree traversal.
BasicUpstart2(start)

.label huff_source = $02
.label huff_remaining = $04
.label huff_head = $06
.label huff_tail = $07
.label huff_next_offset = $08
.label huff_long_base = $09
.label huff_jump = $0a

.macro nextByte() {
    lda huff_tail
    sta huff_head
    lda (huff_source),y
    iny
    bne !ready+
    inc huff_source+1
!ready:
    sta huff_tail
}

* = $1000 "Huffman benchmark and native decoder"
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
!clear:
    lda #0
    .for (var page=0;page<4;page++) {sta $0400+page*$100,x}
    lda #1
    .for (var page=0;page<4;page++) {sta $d800+page*$100,x}
    inx
    bne !clear-
    lda #$18
    sta $d018
    lda #8
    sta $d016
    jsr wait_boundary
    lda #$1b
    sta $d011
benchmark_start:
    jsr wait_boundary
decode_start:
    jsr huffman_decode
decode_end:
    nop
frame_done:
    jmp benchmark_start

huffman_decode:
    lda #<$7000
    sta huff_source
    lda #>$7000
    sta huff_source+1
    lda #<$3000
    sta huff_store+1
    lda #>$3000
    sta huff_store+2
    lda decoded_length
    sta huff_remaining
    lda decoded_length+1
    sta huff_remaining+1
    lda huff_remaining
    bne !length_ready+
    dec huff_remaining+1
!length_ready:
    ldy #0
    lda (huff_source),y
    sta huff_head
    iny
    lda (huff_source),y
    sta huff_tail
    iny
    jmp decode_zero

.var states = List()
decode_zero:
.for (var offset=0;offset<8;offset++) {
    .eval states.add(*)
    .if (offset == 0) {
        ldx huff_head
    } else {
        ldx huff_head
        lda huff_shift_left+offset*$100,x
        ldx huff_tail
        ora huff_shift_right+offset*$100,x
        tax
    }
    lda huff_prefix_length,x
    beq !long+
    clc
    adc #offset
    sta huff_next_offset
    lda huff_prefix_value,x
    jmp huff_emit
!long:
    lda huff_prefix_value,x
    sta huff_long_base
    :nextByte()
    .if (offset == 0) {
        lda huff_head
    } else {
        ldx huff_head
        lda huff_shift_left+offset*$100,x
        ldx huff_tail
        ora huff_shift_right+offset*$100,x
    }
    .for (var bit=0;bit<6;bit++) {lsr}
    ora huff_long_base
    tax
    lda huff_secondary_length,x
    clc
    adc #offset
    sta huff_next_offset
    lda huff_secondary_value,x
    jmp huff_emit
}

huff_emit:
huff_store:
    sta $3000
    inc huff_store+1
    bne !output_ready+
    inc huff_store+2
!output_ready:
    dec huff_remaining
    bne !more+
    lda huff_remaining+1
    beq !done+
    dec huff_remaining+1
!more:
    ldx huff_next_offset
    cpx #8
    bcc !no_advance+
    :nextByte()
!no_advance:
    lda huff_dispatch_low,x
    sta huff_jump
    lda huff_dispatch_high,x
    sta huff_jump+1
    jmp (huff_jump)
!done:
    rts
huff_dispatch_low: .fill 16,<states.get(i&7)
huff_dispatch_high: .fill 16,>states.get(i&7)

wait_boundary:
!leave_high:
    bit $d011
    bmi !leave_high-
!enter_high:
    bit $d011
    bpl !enter_high-
    rts
interrupt_return: rti
decoded_length: .word 261
decoder_code_end:
.assert "Decoder code below font", decoder_code_end <= $2000,true

* = $2000 "Current168-glyph font"
font: .import binary "build/huffman-native/font.bin"

* = $4000 "Two-level Huffman lookup tables"
huff_prefix_value: .import binary "build/huffman-native/prefix-value.bin"
huff_prefix_length: .import binary "build/huffman-native/prefix-length.bin"
huff_secondary_value: .import binary "build/huffman-native/secondary-value.bin"
huff_secondary_length: .import binary "build/huffman-native/secondary-length.bin"

* = $4400 "Byte-alignment lookup tables"
huff_shift_left:
    .for (var shift=0;shift<8;shift++) {.fill 256,(i<<shift)&255}
huff_shift_right:
    .for (var shift=0;shift<8;shift++) {.fill 256,shift==0?0:i>>(8-shift)}
tables_end:
.assert "FiveKiB lookup data", tables_end-$4000,5120

* = $7000 "One compressed frame and safe lookahead"
compressed_frame: .import binary "build/huffman-native/first-frame.bin"
    .byte 0,0
