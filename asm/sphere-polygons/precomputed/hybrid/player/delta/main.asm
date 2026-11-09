// Native HD64 lag-one checker movie. Only the first key image is cached.
// Every later frame copies the current front screen, then applies its real
// serialized skip/literal/repeat packets into the alternating back screen.
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
.label payload_length = $14
.label fill_length = $16
.label packet_left = $18
.label packet_value = $19
.label packed_bits = $1a
.label bits_left = $1b
.label row_left = $1c
.label row_index = $1d
.label packet_tag = $1e
.label key_flag = $1f
.label fill_scratch = $1000
.label first_key_cache = $1400

.var movieData = LoadBinary("../build/assets/checker-64-smooth-delta1-lag1.hd64")
.assert "HD64 magic H", movieData.get(0), 72
.assert "HD64 magic D", movieData.get(1), 68
.assert "HD64 version", movieData.get(4), 1
.assert "HD64 width", movieData.get(5), 40
.assert "HD64 height", movieData.get(6), 25
.assert "HD64 frames", movieData.get(7)+256*movieData.get(8), 64
.assert "HD64 circle layout", movieData.get(9), 2
.assert "HD64 PackBits fill", movieData.get(10), 1
.assert "HD64 raw edge presence", movieData.get(11), 5
.assert "HD64 64-cell packet codec", movieData.get(12), 1
.assert "HD64 previous-image reference", movieData.get(13), 1
.assert "First frame is key", movieData.get(65)&128, 128
.assert "Fixed verified HD64 bytes", movieData.getSize(), 15169

* = $2000 "Immutable mathematical font"
font:
    .import binary "../build/assets/font.bin"
.assert "Font bytes", *-font, 2048

* = $3000 "HD64 lag-one player"
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
!clear:
    lda #0
    .for (var page=0; page<4; page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for (var page=0; page<4; page++) { sta $d800+page*$100,x }
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

    // Startup-only work: parse and decode the actual first HD64 key image.
    lda #<movie_frames
    sta frame_ptr
    lda #>movie_frames
    sta frame_ptr+1
    jsr parse_frame
    jsr decode_key
    lda next_frame_ptr
    sta first_delta_ptr
    lda next_frame_ptr+1
    sta first_delta_ptr+1
    lda back_screen_hi
    ldy #>first_key_cache
    jsr copy_buffer
    lda #$1b
    sta $d011

render_start:
    lda frame_index
    bne !delta+
    // Reuse the decoded real key at every loop wrap. This copy is timed.
    lda #>first_key_cache
    ldy back_screen_hi
    jsr copy_buffer
    lda first_delta_ptr
    sta frame_ptr
    lda first_delta_ptr+1
    sta frame_ptr+1
    jmp render_end
!delta:
    // Lag-one synchronization is explicit: preserve the complete last image
    // in the alternating destination before applying skips and writes.
    lda front_screen_hi
    ldy back_screen_hi
    jsr copy_buffer
    jsr parse_frame
    lda key_flag
    bpl !patch_record+
    jmp invalid_movie
!patch_record:
    lda #0
    sta destination_ptr
    lda back_screen_hi
    sta destination_ptr+1
    jsr decode_delta
    lda next_frame_ptr
    sta frame_ptr
    lda next_frame_ptr+1
    sta frame_ptr+1
render_end:
    jsr wait_raster
    // Predictive images naturally need two PAL fields. The cached key fits
    // one, so spend one additional wrap here to preserve uniform cadence.
    lda frame_index
    bne !cadence_ready+
    jsr wait_raster
!cadence_ready:
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
    inc frame_index
    lda frame_index
    cmp #64
    bne !next+
    lda #0
    sta frame_index
!next:
    jmp render_start

// Copies four complete pages. A=source high byte, Y=destination high byte.
// These pages include the 24 unused screen bytes, which remain zero.
copy_buffer:
    sta copy_read0+2
    clc
    adc #1
    sta copy_read1+2
    adc #1
    sta copy_read2+2
    adc #1
    sta copy_read3+2
    tya
    sta copy_write0+2
    clc
    adc #1
    sta copy_write1+2
    adc #1
    sta copy_write2+2
    adc #1
    sta copy_write3+2
    ldx #0
!copy:
copy_read0:  lda $0400,x
copy_write0: sta $0c00,x
copy_read1:  lda $0500,x
copy_write1: sta $0d00,x
copy_read2:  lda $0600,x
copy_write2: sta $0e00,x
copy_read3:  lda $0700,x
copy_write3: sta $0f00,x
    inx
    bne !copy-
    rts

// Parse the real two-byte HD64 length/key tag, then locate the following record.
parse_frame:
    ldy #0
    lda (frame_ptr),y
    sta payload_length
    iny
    lda (frame_ptr),y
    sta key_flag
    and #127
    sta payload_length+1
    clc
    lda frame_ptr
    adc #2
    sta source_ptr
    lda frame_ptr+1
    adc #0
    sta source_ptr+1
    clc
    lda source_ptr
    adc payload_length
    sta next_frame_ptr
    lda source_ptr+1
    adc payload_length+1
    sta next_frame_ptr+1
    rts

decode_delta:
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
    cmp next_frame_ptr
    bne !packet-
    lda source_ptr+1
    cmp next_frame_ptr+1
    bne !packet-
    // Complete streams cover exactly 1,000 cells, including skipped tails.
    lda destination_ptr
    cmp #232
    beq !low_ok+
    jmp invalid_movie
!low_ok:
    lda back_screen_hi
    clc
    adc #3
    cmp destination_ptr+1
    beq !high_ok+
    jmp invalid_movie
!high_ok:
    rts

// HD64 key payload: fillLengthLE16, PackBits fill bytes, edge map and glyphs.
decode_key:
    jsr read_source
    sta fill_length
    jsr read_source
    sta fill_length+1
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
    rts

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
    // These instructions preserve the consumed bit's carry flag.
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
    bne !nonempty+
    jmp invalid_movie
!nonempty:
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
first_delta_ptr: .word 0
delta_control_end:
delta_code_end:

* = ((*+$ff)&$ff00) "Serialized HD64 lag-one checker movie"
movie:
animation:
    .import binary "../build/assets/checker-64-smooth-delta1-lag1.hd64"
.label movie_layout = movie+14
.label movie_frames = movie+64
movie_end:
animation_end:
.assert "Movie below I/O", movie_end <= $d000, true
