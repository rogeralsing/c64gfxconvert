// Exact precomputed per-face span lookup, live native character fill and resolve.
BasicUpstart2(start)
.const CLIP_TILE_COUNT = 148
.const GLYPH_SOURCE_COUNT = 148
#import "build/abi.asm"
.label movie_ptr = $40
.label visible_bits = $47
.label current_face_index = $4b
.label span_base = $4c
.label pattern_ptr = $4d
.label pattern_offset = $4f
.label visible_faces = $1580
.var movieData = LoadBinary("build/assets/spans.sa64")
.assert "SA64 version", movieData.get(4), 1
.assert "SA64 faces", movieData.get(5), 36
.assert "SA64 frames", movieData.get(6)+256*movieData.get(7), 64
.assert "SA64 nibble codec", movieData.get(10), 1

* = $2000 "Fixed mathematical font"
font: .import binary "build/assets/font.bin"
.assert "Font bytes", *-font, 2048

* = $3000 "SA64 character span player"
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
    lda #15
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

render_start:
decode_start:
    jsr decode_frame
decode_end:
    nop
    jsr render_polygons
resolve_start:
    jsr resolve_screen
resolve_end:
    nop
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
    cmp #64
    bne !next+
    lda #0
    sta frame_index
!next:
    jmp render_start

decode_frame:
    lda frame_index
    bne !pointer_ready+
    lda #<movie_first_frame
    sta movie_ptr
    lda #>movie_first_frame
    sta movie_ptr+1
!pointer_ready:
    ldx #0
!visibility:
    jsr read_movie
    sta visible_faces,x
    inx
    cpx #5
    bne !visibility-
    rts

read_movie:
    ldy #0
    lda (movie_ptr),y
    inc movie_ptr
    bne !done+
    inc movie_ptr+1
!done:
    rts

read_pattern:
    ldy #0
    lda (pattern_ptr),y
    inc pattern_ptr
    bne !done+
    inc pattern_ptr+1
!done:
    rts

decode_face_spans:
    jsr read_movie
    sta raster_sample
    jsr read_movie
    sta span_base
    jsr read_movie
    sta pattern_offset
    jsr read_movie
    pha
    lda pattern_offset
    clc
    adc #<span_pool
    sta pattern_ptr
    pla
    adc #>span_pool
    sta pattern_ptr+1
    jsr read_pattern
    clc
    adc raster_sample
    sta raster_sample_end
    ldx raster_sample
    cpx raster_sample_end
    beq !done+
    jsr read_pattern
    clc
    adc span_base
    sta raster_x0
    sta span_left,x
    jsr read_pattern
    clc
    adc span_base
    sta raster_x1
    sta span_right,x
    inx
    cpx raster_sample_end
    beq !done+
!sample:
    jsr read_pattern
    cmp #255
    beq !absolute+
    pha
    and #15
    sec
    sbc #7
    clc
    adc raster_x0
    sta raster_x0
    sta span_left,x
    pla
    lsr
    lsr
    lsr
    lsr
    sec
    sbc #7
    clc
    adc raster_x1
    sta raster_x1
    sta span_right,x
    jmp !next+
!absolute:
    jsr read_pattern
    clc
    adc span_base
    sta raster_x0
    sta span_left,x
    jsr read_pattern
    clc
    adc span_base
    sta raster_x1
    sta span_right,x
!next:
    inx
    cpx raster_sample_end
    bcc !sample-
!done:
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
front_screen_hi: .byte 4
back_screen_hi: .byte 12
bit_masks: .byte 1,2,4,8,16,32,64,128

#import "build/raster.asm"
player_code_end:
.assert "Code below static assets", player_code_end <= $4000, true

.align $100
raster_assets_start:
glyph_lut: .import binary "build/assets/glyph-lut.bin"
glyph_compact: .import binary "build/assets/glyph-compact.bin"
limb_remap: .import binary "build/assets/limb-remap.bin"
clip_records: .import binary "build/assets/clip-records.bin"
sample_row_lo: .import binary "build/assets/sample-row-lo.bin"
sample_row_hi: .import binary "build/assets/sample-row-hi.bin"
left_masks: .import binary "build/assets/left-masks.bin"
right_masks: .import binary "build/assets/right-masks.bin"
raster_assets_end:
animation:
    .import binary "build/assets/spans.sa64"
animation_end:
.label movie_counts = animation+12
.label span_pool = animation+48
.label movie_first_frame = span_pool+movieData.get(8)+256*movieData.get(9)
.assert "Remap page aligned", <limb_remap, 0
.assert "All assets below I/O", animation_end <= $d000, true
