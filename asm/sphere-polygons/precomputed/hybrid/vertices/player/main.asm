// Precomputed projected vertices, exact character-span rasterization on6502.
BasicUpstart2(start)
.const CLIP_TILE_COUNT = 148
.const GLYPH_SOURCE_COUNT = 148
.label movie_ptr = $40
.label topology_ptr = $42
.label init_faces_left = $44
.label packed_delta = $45
.label visible_shift = $46
.label visible_bits = $47
.label visibility_index = $48
.label init_count = $49
.label init_color = $4a
.label current_face_index = $4b
.label visible_faces = $1580
.label expanded_faces = $1600
.var movieData = LoadBinary("../build/assets/white-delta.pv64")
.assert "PV64 magic", movieData.get(0), 80
.assert "PV64 version", movieData.get(4), 1
.assert "PV64 delta mode", movieData.get(5), 1
.assert "PV64 vertices", movieData.get(6), 62
.assert "PV64 white faces", movieData.get(7), 36
.assert "PV64 frames", movieData.get(8)+256*movieData.get(9), 64
.assert "PV64 vector bits", movieData.get(10), 4
.assert "PV64 codebook pairs", movieData.get(11), 15
.assert "PV64 complete bytes", movieData.getSize(), 2607

* = $2000 "Fixed mathematical font"
font: .import binary "../build/assets/font.bin"
.assert "Font bytes", *-font, 2048

* = $3000 "PV64 character polygon player"
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
    jsr expand_topology
    lda #$1b
    sta $d011

render_start:
decode_start:
    jsr decode_vertices
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

// Expand compact white topology into the unchanged raster's12-byte records.
expand_topology:
    lda #<movie_topology
    sta movie_ptr
    lda #>movie_topology
    sta movie_ptr+1
    lda #<expanded_faces
    sta topology_ptr
    lda #>expanded_faces
    sta topology_ptr+1
    lda #36
    sta init_faces_left
!face:
    lda #0
    ldy #11
!zero:
    sta (topology_ptr),y
    dey
    bpl !zero-
    jsr read_movie
    pha
    and #127
    sta init_count
    ldy #0
    sta (topology_ptr),y
    pla
    asl
    lda #0
    rol
    iny
    sta (topology_ptr),y
    ldx #0
!index:
    jsr read_movie
    pha
    txa
    clc
    adc #5
    tay
    pla
    sta (topology_ptr),y
    inx
    cpx init_count
    bne !index-
    clc
    lda topology_ptr
    adc #12
    sta topology_ptr
    bcc !same_page+
    inc topology_ptr+1
!same_page:
    dec init_faces_left
    bne !face-
    rts

decode_vertices:
    lda frame_index
    bne !delta+
    lda #<movie_first_xy
    sta movie_ptr
    lda #>movie_first_xy
    sta movie_ptr+1
    ldx #0
!initial:
    jsr read_movie
    sta projected_x,x
    jsr read_movie
    sta projected_y,x
    inx
    cpx #62
    bne !initial-
    jmp !visibility+
!delta:
    ldx #0
!pair:
    jsr read_movie
    sta packed_delta
    and #15
    jsr add_vector
    inx
    lda packed_delta
    lsr
    lsr
    lsr
    lsr
    jsr add_vector
    inx
    cpx #62
    bne !pair-
!visibility:
    ldx #0
!visible_byte:
    jsr read_movie
    sta visible_faces,x
    inx
    cpx #5
    bne !visible_byte-
    rts

add_vector:
    asl
    tay
    lda movie_codebook,y
    clc
    adc projected_x,x
    sta projected_x,x
    iny
    lda movie_codebook,y
    clc
    adc projected_y,x
    sta projected_y,x
    rts

read_movie:
    ldy #0
    lda (movie_ptr),y
    inc movie_ptr
    bne !done+
    inc movie_ptr+1
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

#import "raster.asm"
player_code_end:
.assert "Code below static assets", player_code_end <= $4000, true

* = $4000 "Character raster lookup assets"
ratio_q: .import binary "../build/assets/ratio-q.bin"
.align $100
ratio_r: .import binary "../build/assets/ratio-r.bin"
ratio_row_lo: .import binary "../build/assets/ratio-row-lo.bin"
ratio_row_hi: .import binary "../build/assets/ratio-row-hi.bin"
sample_y: .import binary "../build/assets/sample-y.bin"
sample_gap: .import binary "../build/assets/sample-gap.bin"
first_sample: .import binary "../build/assets/first-sample.bin"
sample_row_lo: .import binary "../build/assets/sample-row-lo.bin"
sample_row_hi: .import binary "../build/assets/sample-row-hi.bin"
left_masks: .import binary "../build/assets/left-masks.bin"
right_masks: .import binary "../build/assets/right-masks.bin"
full_masks: .import binary "../build/assets/full-masks.bin"
.align $100
glyph_lut: .import binary "../build/assets/glyph-lut.bin"
.align $100
glyph_compact: .import binary "../build/assets/glyph-compact.bin"
clip_records: .import binary "../build/assets/clip-records.bin"
.align $100
limb_remap: .import binary "../build/assets/limb-remap.bin"
raster_assets_end:
.align $100
animation:
    .import binary "../build/assets/white-delta.pv64"
animation_end:
.label movie_topology = animation+12
.label movie_codebook = animation+180
.label movie_first_xy = animation+210
.assert "All assets below I/O", animation_end <= $d000, true
