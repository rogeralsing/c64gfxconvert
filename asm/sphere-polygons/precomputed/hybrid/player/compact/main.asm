// Compact native playback of independent HC64 checker frames.
BasicUpstart2(start)

.label source_ptr = $02
.label frame_ptr = $04
.label fill_end_ptr = $06
.label edge_ptr = $08
.label glyph_ptr = $0a
.label next_frame_ptr = $0c
.label destination_ptr = $0e
.label layout_ptr = $10
.label row_base = $12
.label fill_length = $14
.label edge_length = $16
.label packet_left = $18
.label packet_value = $19
.label packed_bits = $1a
.label bits_left = $1b
.label row_left = $1c
.label row_index = $1d
.label saved_value = $1e
.label fill_scratch = $1000

.var movieData = LoadBinary("../build/assets/checker-64.hc64")
.assert "HC64 width", movieData.get(5), 40
.assert "HC64 height", movieData.get(6), 25
.assert "HC64 frames", movieData.get(7)+256*movieData.get(8), 64
.assert "Circle layout", movieData.get(9), 2
.assert "PackBits fill codec", movieData.get(10), 1
.assert "Raw circle edge codec", movieData.get(11), 5

* = $2000 "Immutable mathematical font"
font:
    .import binary "../build/assets/font.bin"
.assert "Font bytes", *-font, 2048

* = $3000 "Compact HC64 player"
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
    .for(var page=0;page<4;page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for(var page=0;page<4;page++) { sta $d800+page*$100,x }
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
    lda #<movie_frames
    sta frame_ptr
    lda #>movie_frames
    sta frame_ptr+1

render_start:
    // All per-frame header parsing, PackBits work, fill expansion and edge
    // patching are measured before render_end.
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
    sta source_ptr
    lda frame_ptr+1
    adc #0
    sta source_ptr+1
    clc
    lda source_ptr
    adc fill_length
    sta fill_end_ptr
    sta edge_ptr
    lda source_ptr+1
    adc fill_length+1
    sta fill_end_ptr+1
    sta edge_ptr+1
    clc
    lda edge_ptr
    adc edge_length
    sta next_frame_ptr
    lda edge_ptr+1
    adc edge_length+1
    sta next_frame_ptr+1
    clc
    lda edge_ptr
    adc #60
    sta glyph_ptr
    lda edge_ptr+1
    adc #0
    sta glyph_ptr+1
    jsr unpack_fill

    lda #<fill_scratch
    sta source_ptr
    lda #>fill_scratch
    sta source_ptr+1
    jsr start_layout
    jsr start_bits
!fill_row:
    jsr next_layout_row
!fill_cell:
    jsr next_bit
    lda #0
    bcc !fill_value+
    lda #15
!fill_value:
    ldy #0
    sta (destination_ptr),y
    jsr advance_destination
    dec row_left
    bne !fill_cell-
    jsr advance_row
    bne !fill_row-

    lda edge_ptr
    sta source_ptr
    lda edge_ptr+1
    sta source_ptr+1
    jsr start_layout
    jsr start_bits
!edge_row:
    jsr next_layout_row
!edge_cell:
    jsr next_bit
    bcc !no_edge+
    ldy #0
    lda (glyph_ptr),y
    sta (destination_ptr),y
    inc glyph_ptr
    bne !no_edge+
    inc glyph_ptr+1
!no_edge:
    jsr advance_destination
    dec row_left
    bne !edge_cell-
    jsr advance_row
    bne !edge_row-

    lda next_frame_ptr
    sta frame_ptr
    lda next_frame_ptr+1
    sta frame_ptr+1
render_end:
    jsr wait_raster
    ldx front_screen_hi
    lda back_screen_hi
    sta front_screen_hi
    stx back_screen_hi
    cmp #4
    beq !screen_first+
    lda #$38
    bne !present+
!screen_first:
    lda #$18
!present:
    sta $d018
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // frame_index still identifies the visible frame at this checkpoint.
    inc frame_index
    lda frame_index
    cmp #64
    bne !next+
    lda #0
    sta frame_index
    lda #<movie_frames
    sta frame_ptr
    lda #>movie_frames
    sta frame_ptr+1
!next:
    jmp render_start

unpack_fill:
    ldx #0
!packet:
    jsr read_source
    cmp #128
    bcc !literal+
    bne !repeat_control+
    jmp invalid_movie
!repeat_control:
    eor #255
    clc
    adc #2
    sta packet_left
    jsr read_source
    sta packet_value
!repeat:
    lda packet_value
    sta fill_scratch,x
    inx
    dec packet_left
    bne !repeat-
    jmp !more+
!literal:
    clc
    adc #1
    sta packet_left
!copy:
    jsr read_source
    sta fill_scratch,x
    inx
    dec packet_left
    bne !copy-
!more:
    cpx #60
    bcc !packet-
    beq !count_ok+
    jmp invalid_movie
!count_ok:
    lda source_ptr
    cmp fill_end_ptr
    beq !low_ok+
    jmp invalid_movie
!low_ok:
    lda source_ptr+1
    cmp fill_end_ptr+1
    beq !high_ok+
    jmp invalid_movie
!high_ok:
    rts

read_source:
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !done+
    inc source_ptr+1
!done:
    rts

start_bits:
    jsr read_source
    sta packed_bits
    lda #8
    sta bits_left
    rts

next_bit:
    asl packed_bits
    dec bits_left
    bne !done+
    // read_source, INC, LDA and STA preserve carry from the consumed bit.
    jsr read_source
    sta packed_bits
    lda #8
    sta bits_left
!done:
    rts

start_layout:
    lda #<movie_layout
    sta layout_ptr
    lda #>movie_layout
    sta layout_ptr+1
    lda #0
    sta row_base
    sta row_index
    lda back_screen_hi
    sta row_base+1
    rts

next_layout_row:
    ldy #0
    lda (layout_ptr),y
    clc
    adc row_base
    sta destination_ptr
    lda row_base+1
    adc #0
    sta destination_ptr+1
    iny
    lda (layout_ptr),y
    sta row_left
    beq invalid_movie
    clc
    lda layout_ptr
    adc #2
    sta layout_ptr
    bcc !done+
    inc layout_ptr+1
!done:
    rts

advance_destination:
    inc destination_ptr
    bne !done+
    inc destination_ptr+1
!done:
    rts

advance_row:
    clc
    lda row_base
    adc #40
    sta row_base
    bcc !same_page+
    inc row_base+1
!same_page:
    inc row_index
    lda row_index
    cmp #25
    rts

wait_raster:
!high:
    bit $d011
    bpl !high-
!low:
    bit $d011
    bmi !low-
    rts
invalid_movie:
    brk
    jmp invalid_movie
interrupt_return:
    rti

frame_index: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 12
compact_code_end:
.assert "Compact player below assets", compact_code_end <= $4000, true

* = $4000 "Serialized HC64 checker movie"
movie:
    .import binary "../build/assets/checker-64.hc64"
.label movie_layout = movie+12
.label movie_frames = movie+62
movie_end:
.assert "Movie below I/O", movie_end <= $d000, true
