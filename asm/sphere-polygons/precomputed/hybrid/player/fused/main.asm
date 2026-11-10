// HC64 playback: PackBits fill plus exact edge presence/glyphs, one final write
// per selected character. Kernel addresses derive only from serialized layout.
.var movieData = LoadBinary("../build/assets/checker-64.hc64")
.const FRAME_COUNT = movieData.get(7) + movieData.get(8)*256
.const EXPANDED_BYTES = 60
.label frame_ptr = $02
.label fill_ptr = $04
.label edge_ptr = $06
.label glyph_ptr = $08
.label next_ptr = $0a
.label fill_length = $0c
.label edge_length = $0e
.label packet_remaining = $10
.label repeated_value = $11
.label glyph_index_scratch = $12
.label edge_current = $13
.label fill_bits = $1000

.assert "HC64 version", movieData.get(4), 1
.assert "HC64 width", movieData.get(5), 40
.assert "HC64 height", movieData.get(6), 25
.assert "HC64 frame count", FRAME_COUNT, 64
.assert "HC64 circle layout", movieData.get(9), 2
.assert "HC64 PackBits fill", movieData.get(10), 1
.assert "HC64 raw circle edge map", movieData.get(11), 5

BasicUpstart2(start)

* = $2000 "Fixed mathematical font"
font:
    .import binary "../build/assets/font.bin"
.assert "Fixed font size", *-font, 2048

* = $2800 "Fill-bit glyph lookup planes"
fill_planes:
    .for (var bit = 0; bit < 8; bit++) {
        .fill 256, (i & (128 >> bit)) != 0 ? 15 : 0
    }

* = $3000 "Fused HC64 player control"
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
    lda #15
    sta $d019
    lda #$0b
    sta $d011
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
    .for (var page = 0; page < 4; page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for (var page = 0; page < 4; page++) {
        sta $d800+page*$100,x
    }
    inx
    bne !clear-
    lda #4
    sta front_screen_hi
    lda #12
    sta back_screen_hi
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    lda #$1b
    sta $d011
    lda #<first_frame
    sta frame_ptr
    lda #>first_frame
    sta frame_ptr+1

main:
render_start:
    // Both packet lengths are parsed from the current HC64 frame header.
    ldy #0
    lda (frame_ptr),y
    sta fill_length
    iny
    lda (frame_ptr),y
    sta fill_length+1
    iny
    lda (frame_ptr),y
    sta edge_length
    iny
    lda (frame_ptr),y
    sta edge_length+1
    clc
    lda frame_ptr
    adc #4
    sta fill_ptr
    lda frame_ptr+1
    adc #0
    sta fill_ptr+1
    clc
    lda fill_ptr
    adc fill_length
    sta edge_ptr
    lda fill_ptr+1
    adc fill_length+1
    sta edge_ptr+1
    clc
    lda edge_ptr
    adc edge_length
    sta next_ptr
    lda edge_ptr+1
    adc edge_length+1
    sta next_ptr+1
    clc
    lda edge_ptr
    adc #EXPANDED_BYTES
    sta glyph_ptr
    lda edge_ptr+1
    adc #0
    sta glyph_ptr+1
    jsr decode_fill
    ldy #0                          // Exact edge glyphs are read in layout order.
    lda back_screen_hi
    cmp #4
    beq !screen_a+
    jsr kernel_0c00
    jmp !decoded+
!screen_a:
    jsr kernel_0400
!decoded:
    lda next_ptr
    sta frame_ptr
    lda next_ptr+1
    sta frame_ptr+1
render_end:
    jsr wait_raster
    ldx front_screen_hi
    lda back_screen_hi
    sta front_screen_hi
    stx back_screen_hi
    cmp #4
    beq !front_a+
    lda #$38
    bne !present+
!front_a:
    lda #$18
!present:
    sta $d018
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // frame_index describes the frame visible at this inspection checkpoint.
    inc frame_index
    lda frame_index
    cmp #FRAME_COUNT
    bcs !wrap+
    jmp main
!wrap:
    lda #0
    sta frame_index
    lda #<first_frame
    sta frame_ptr
    lda #>first_frame
    sta frame_ptr+1
    jmp main

decode_fill:
    ldx #0
!packet:
    jsr read_fill
    cmp #128
    beq invalid_packet
    bcs !repeat+
    clc
    adc #1
    sta packet_remaining
!literal:
    jsr read_fill
    sta fill_bits,x
    inx
    dec packet_remaining
    bne !literal-
    jmp !next+
!repeat:
    eor #255
    clc
    adc #2
    sta packet_remaining
    jsr read_fill
    sta repeated_value
!run:
    lda repeated_value
    sta fill_bits,x
    inx
    dec packet_remaining
    bne !run-
!next:
    cpx #EXPANDED_BYTES
    bcc !packet-
    rts

read_fill:
    ldy #0
    lda (fill_ptr),y
    inc fill_ptr
    bne !same_page+
    inc fill_ptr+1
!same_page:
    rts

invalid_packet:
    lda #2
    sta $d020
    jmp invalid_packet

wait_raster:
!high:
    bit $d011
    bpl !high-
!low:
    bit $d011
    bmi !low-
    rts

interrupt_return:
    rti

frame_index:        .byte 0
frame_counter:      .word 0
front_screen_hi:    .byte 4
back_screen_hi:     .byte 12
control_end:
.assert "Control code below encoded data", control_end <= $4000, true

* = $4000 "Serialized HC64 sequence"
movie:
    .fill movieData.getSize(), movieData.get(i)
.label first_frame = movie+62
movie_end:
.assert "Encoded data below playback kernels", movie_end <= $9000, true

* = $9000 "Fused direct-store kernels"
kernel_0400:
    DrawFrame($0400)
kernel_0c00:
    DrawFrame($0c00)
kernels_end:
.assert "Playback kernels below I/O", kernels_end <= $d000, true

.macro DrawFrame(screenBase) {
    .var ordinal = 0
    .for (var row = 0; row < 25; row++) {
        .var firstColumn = movieData.get(12+row*2)
        .var count = movieData.get(13+row*2)
        .assert "Serialized row must fit screen", firstColumn+count <= 40, true
        .for (var column = 0; column < count; column++) {
            .if ((ordinal & 7) == 0) {
                // The glyph index survives the raw presence-byte load.
                sty glyph_index_scratch
                ldy #floor(ordinal/8)
                lda (edge_ptr),y
                sta edge_current
                ldy glyph_index_scratch
                ldx fill_bits+floor(ordinal/8)
            }
            lda fill_planes+(ordinal&7)*256,x
            asl edge_current
            bcc !fill+
            lda (glyph_ptr),y
            iny
!fill:
            sta screenBase+row*40+firstColumn+column
            .eval ordinal = ordinal+1
        }
    }
    .assert "Serialized circle has 475 cells", ordinal, 475
    rts
}
