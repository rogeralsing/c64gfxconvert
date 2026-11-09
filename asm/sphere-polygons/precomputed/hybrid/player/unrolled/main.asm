// Same serialized HC64 source as the compact player, decoded into text screens.
#import "build/constants.asm"
.label frame_ptr = $02
.label fill_ptr = $04
.label edge_ptr = $06
.label glyph_ptr = $08
.label next_frame_ptr = $0a
.label fill_length = $0c
.label edge_length = $0e
.label packet_count = $10
.label fill_scratch = $1800
.label edge_scratch = $1840

BasicUpstart2(start)

* = $1000 "Eight mathematical fill-bit lookup pages"
fill_tables:
#import "build/tables.asm"
fill_tables_end:
.assert "Fill lookup bytes", fill_tables_end-fill_tables, 2048

* = $2000 "Unchanged mathematical font"
font:
    .import binary "../build/assets/font.bin"
.assert "Fixed font bytes", *-font, 2048

* = $2800 "HC64 player core"
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
    .for (var page=0;page<4;page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for (var page=0;page<4;page++) {
        sta $d800+page*$100,x
    }
    inx
    bne !clear-
    // Parse the global count once; per-frame lengths are parsed every render.
    lda animation+7
    sta frame_count
    lda #<(animation+FIRST_FRAME_OFFSET)
    sta frame_ptr
    lda #>(animation+FIRST_FRAME_OFFSET)
    sta frame_ptr+1
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

main:
render_start:
    jsr parse_frame
    jsr decode_fill
    // Copy the 60 source map bytes. The glyph stream remains in the HC64 file.
    ldy #0
    .for (var byte=0;byte<EDGE_MAP_BYTES;byte++) {
        lda (edge_ptr),y
        sta edge_scratch+byte
        .if (byte != EDGE_MAP_BYTES-1) { iny }
    }
    lda back_screen_hi
    cmp #4
    beq !screen_a+
    jsr expand_b
    jmp render_end
!screen_a:
    jsr expand_a
render_end:
    jsr wait_raster
    ldx front_screen_hi
    lda back_screen_hi
    sta front_screen_hi
    stx back_screen_hi
    cmp #4
    beq !first+
    lda #$38
    bne !present+
!first:
    lda #$18
!present:
    sta $d018
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    inc frame_index
    lda frame_index
    cmp frame_count
    bcc !next+
    lda #0
    sta frame_index
    lda #<(animation+FIRST_FRAME_OFFSET)
    sta frame_ptr
    lda #>(animation+FIRST_FRAME_OFFSET)
    sta frame_ptr+1
    jmp main
!next:
    lda next_frame_ptr
    sta frame_ptr
    lda next_frame_ptr+1
    sta frame_ptr+1
    jmp main

// Consume the real four-byte frame header and derive every source pointer.
parse_frame:
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
    adc #EDGE_MAP_BYTES
    sta glyph_ptr
    lda edge_ptr+1
    adc #0
    sta glyph_ptr+1
    clc
    lda edge_ptr
    adc edge_length
    sta next_frame_ptr
    lda edge_ptr+1
    adc edge_length+1
    sta next_frame_ptr+1
    rts

// Standard PackBits, expanded to exactly 60 scratch bytes. The shared asset
// validator guarantees a byte-indexed source and rejects reserved control128.
decode_fill:
    ldx #0
    ldy #0
!packet:
    lda (fill_ptr),y
    iny
    cmp #128
    bcs !repeat+
    adc #1
    sta packet_count
!literal:
    lda (fill_ptr),y
    iny
    sta fill_scratch,x
    inx
    dec packet_count
    bne !literal-
    cpx #FILL_BYTES
    bcc !packet-
    rts
!repeat:
    eor #255
    clc
    adc #2
    sta packet_count
    lda (fill_ptr),y
    iny
!copies:
    sta fill_scratch,x
    inx
    dec packet_count
    bne !copies-
    cpx #FILL_BYTES
    bcc !packet-
    rts

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
frame_index: .byte 0
frame_counter: .word 0
frame_count: .byte 0
front_screen_hi: .byte 4
back_screen_hi: .byte 12
core_end:
.assert "Core stays before unrolled routines", core_end <= $3000, true

* = $3000 "Two unrolled destination routines"
unrolled_start:
#import "build/routines.asm"
unrolled_end:
.align $100
animation:
    .import binary "../build/assets/checker-64.hc64"
animation_end:
.assert "All emitted player bytes stay below I/O", animation_end <= $d000, true
