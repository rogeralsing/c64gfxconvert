// Huge checker sphere: replay face spans, fill coverage and resolve fixed glyphs.
// Sources: 0 raw spans, 1 raw XY, 2 packed spans, 3 delta XY, 4 edge paths.
BasicUpstart2(start)
.import source "build/native-geometry/config.inc"

.label source_ptr = $02
.label cover_ptr = $04
.label clip_ptr = $06
.label screen_ptr = $08
.label remap_ptr = $0a
.label faces_left = $0c
.label first_sample = $0e
.label end_sample = $0f
.label current_sample = $10
.label left_col = $11
.label right_col = $12
.label left_mask = $13
.label right_mask = $14
.label mask_part = $15
.label word_lo = $16
.label word_hi = $17
.label previous_left = $18
.label previous_right = $1a
.label packed_delta = $1c
.label clip_left = $1d
.label coverage = $1000
.label span_left_col = $1400
.label span_right_col = $1480
.label span_left_frac = $1500
.label span_right_frac = $1580

* = $2000 "Immutable average font"
font: .import binary "build/geometry/font.bin"
.assert "256 eight-byte glyphs", *-font, 2048

* = $3000 "Native geometry fill benchmark"
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
!init:
    lda #0
    .for (var page=0; page<4; page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for (var page=0; page<4; page++) { sta $d800+page*$100,x }
    inx
    bne !init-
    lda #4
    sta front_screen_hi
    lda #12
    sta back_screen_hi
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    .if (SOURCE_KIND==3) { jsr prepare_initial_source }
    jsr wait_boundary
    lda #$1b
    sta $d011
render_start:
    lda #<movie
    sta source_ptr
    lda #>movie
    sta source_ptr+1
clear_start:
    jsr clear_coverage
clear_end:
    nop
raster_start:
    jsr render_faces
raster_end:
    nop
resolve_start:
    jsr resolve_screen
resolve_end:
    nop
render_end:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // Old front has completed scanout; the new back image is ready to present.
    lda front_screen_hi
    ldx back_screen_hi
    stx front_screen_hi
    sta back_screen_hi
    txa
    asl
    asl
    ora #8
    sta $d018
    jmp render_start

clear_coverage:
    lda #0
    ldx #0
!clear:
    sta coverage,x
    sta coverage+$100,x
    sta coverage+$200,x
    sta coverage+$300,x
    inx
    bne !clear-
    rts

render_faces:
    .if (SOURCE_KIND == 1 || SOURCE_KIND == 3 || SOURCE_KIND == 4) { jsr prepare_source }
    jsr read_source
    sta faces_left
    jsr read_source
    sta faces_left+1
!face:
    lda faces_left
    ora faces_left+1
    beq !done+
    .if (SOURCE_KIND == 1 || SOURCE_KIND == 3 || SOURCE_KIND == 4) { jsr prepare_face } else { jsr span_prepare_face }
    lda first_sample
    sta current_sample
    jsr fill_face
    lda faces_left
    bne !decrement+
    dec faces_left+1
!decrement:
    dec faces_left
    jmp !face-
!done:
    rts

span_prepare_face:
    jsr read_source
    sta first_sample
    tax
    jsr read_source
    clc
    adc first_sample
    sta end_sample
!sample:
    .if (SOURCE_KIND == 2) {
        cpx first_sample
        beq !absolute+
        jsr read_source
        cmp #255
        beq !absolute+
        sta packed_delta
        and #15
        tay
        clc
        lda previous_left
        adc delta_lo,y
        sta previous_left
        lda previous_left+1
        adc delta_hi,y
        sta previous_left+1
        lda packed_delta
        lsr
        lsr
        lsr
        lsr
        tay
        clc
        lda previous_right
        adc delta_lo,y
        sta previous_right
        lda previous_right+1
        adc delta_hi,y
        sta previous_right+1
        jmp !convert+
    }
!absolute:
    jsr read_source
    sta previous_left
    jsr read_source
    sta previous_left+1
    jsr read_source
    sta previous_right
    jsr read_source
    sta previous_right+1
!convert:
    lda previous_left
    and #7
    sta span_left_frac,x
    lda previous_left+1
    lsr
    lda previous_left
    ror
    lsr
    lsr
    sta span_left_col,x
    lda previous_right
    and #7
    sta span_right_frac,x
    lda previous_right+1
    lsr
    lda previous_right
    ror
    lsr
    lsr
    sta span_right_col,x
    inx
    cpx end_sample
    bcc !sample-
    rts

read_source:
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !done+
    inc source_ptr+1
!done:
    rts

fill_face:
!sample:
    ldx current_sample
    cpx end_sample
    bcc !active+
    rts
!active:
    lda row_offset_lo,x
    sta cover_ptr
    lda row_offset_hi,x
    clc
    adc #>coverage
    sta cover_ptr+1
    lda mask_bases,x
    sta mask_part
    .if (FAST_FILL) {
        bne !individual+
        jsr try_triplet
        bcc !individual+
        inc current_sample
        inc current_sample
        jmp !next+
    }
!individual:
    lda span_left_col,x
    sta left_col
    lda span_right_col,x
    sta right_col
    lda span_left_frac,x
    ora mask_part
    tay
    lda left_masks,y
    sta left_mask
    lda span_right_frac,x
    ora mask_part
    tay
    lda right_masks,y
    sta right_mask
    lda left_col
    cmp right_col
    bcc !multiple+
    bne !next+
    lda left_mask
    and right_mask
    beq !next+
    ldy left_col
    ora (cover_ptr),y
    sta (cover_ptr),y
    jmp !next+
!multiple:
    ldy left_col
    lda left_mask
    beq !interior_start+
    ora (cover_ptr),y
    sta (cover_ptr),y
!interior_start:
    iny
    cpy right_col
    bcs !right+
!interior:
    lda full_masks,x
    ora (cover_ptr),y
    sta (cover_ptr),y
    iny
    cpy right_col
    bcc !interior-
!right:
    lda right_mask
    beq !next+
    ora (cover_ptr),y
    sta (cover_ptr),y
!next:
    inc current_sample
    jmp !sample-

try_triplet:
    txa
    clc
    adc #2
    cmp end_sample
    bcs !fallback+
    lda span_left_col,x
    cmp span_left_col+1,x
    bne !fallback+
    cmp span_left_col+2,x
    bne !fallback+
    sta left_col
    lda span_right_col,x
    cmp span_right_col+1,x
    bne !fallback+
    cmp span_right_col+2,x
    bne !fallback+
    sta right_col
    jmp !combine+
!fallback:
    clc
    rts
!combine:
    ldy span_left_frac,x
    lda left_masks,y
    ldy span_left_frac+1,x
    ora left_masks+8,y
    ldy span_left_frac+2,x
    ora left_masks+16,y
    sta left_mask
    ldy span_right_frac,x
    lda right_masks,y
    ldy span_right_frac+1,x
    ora right_masks+8,y
    ldy span_right_frac+2,x
    ora right_masks+16,y
    sta right_mask
    lda left_col
    cmp right_col
    bcc !multiple+
    bne !processed+
    lda left_mask
    and right_mask
    beq !processed+
    ldy left_col
    ora (cover_ptr),y
    sta (cover_ptr),y
    jmp !processed+
!multiple:
    ldy left_col
    lda left_mask
    beq !interior_start+
    ora (cover_ptr),y
    sta (cover_ptr),y
!interior_start:
    iny
    cpy right_col
    bcs !right+
    lda #255
!interior:
    sta (cover_ptr),y
    iny
    cpy right_col
    bcc !interior-
!right:
    lda right_mask
    beq !processed+
    ora (cover_ptr),y
    sta (cover_ptr),y
!processed:
    sec
    rts

resolve_screen:
    lda back_screen_hi
    sta store0+2
    clc
    adc #1
    sta store1+2
    adc #1
    sta store2+2
    adc #1
    sta store3+2
    ldx #0
!resolve:
    lda coverage,x
    tay
    lda glyph_lut,y
store0:
    sta $0400,x
    lda coverage+$100,x
    tay
    lda glyph_lut,y
store1:
    sta $0500,x
    lda coverage+$200,x
    tay
    lda glyph_lut,y
store2:
    sta $0600,x
    lda coverage+$300,x
    tay
    lda glyph_lut,y
store3:
    sta $0700,x
    inx
    beq !resolved+
    jmp !resolve-
!resolved:
    lda #<clip_records
    sta clip_ptr
    lda #>clip_records
    sta clip_ptr+1
    lda #<CLIP_RECORD_COUNT
    sta clip_left
    lda #>CLIP_RECORD_COUNT
    sta clip_left+1
!clip:
    lda clip_left
    ora clip_left+1
    beq !done+
    ldy #0
    lda (clip_ptr),y
    sta screen_ptr
    iny
    lda (clip_ptr),y
    clc
    adc back_screen_hi
    sta screen_ptr+1
    ldy #0
    lda (screen_ptr),y
    beq !advance+
    tax
    ldy #2
    lda (clip_ptr),y
    clc
    adc #<limb_remap
    sta remap_ptr
    iny
    lda (clip_ptr),y
    adc #>limb_remap
    sta remap_ptr+1
    txa
    tay
    lda (remap_ptr),y
    ldy #0
    sta (screen_ptr),y
!advance:
    clc
    lda clip_ptr
    adc #4
    sta clip_ptr
    bcc !same_page+
    inc clip_ptr+1
!same_page:
    lda clip_left
    bne !decrement+
    dec clip_left+1
!decrement:
    dec clip_left
    jmp !clip-
!done:
    rts

wait_boundary:
!leave:
    bit $d011
    bmi !leave-
!enter:
    bit $d011
    bpl !enter-
    rts
interrupt_return:
    rti
front_screen_hi: .byte 4
back_screen_hi: .byte 12
frame_counter: .word 0
player_code_end:
.assert "Code stays below tables", player_code_end <= $4000, true

* = $4000 "Glyph and span lookup tables"
glyph_lut: .import binary "build/geometry/glyph-lut.bin"
left_masks: .import binary "build/geometry/left-mask.bin"
right_masks: .import binary "build/geometry/right-mask.bin"
full_masks: .for (var i=0; i<25; i++) { .byte $07,$18,$e0 }
row_offset_lo: .import binary "build/geometry/row-offset-lo.bin"
row_offset_hi: .import binary "build/geometry/row-offset-hi.bin"
mask_bases: .for (var i=0; i<25; i++) { .byte 0,8,16 }
delta_lo: .for (var i=0; i<16; i++) { .byte (i-7)&255 }
delta_hi: .for (var i=0; i<16; i++) { .byte i<7 ? 255 : 0 }
lookup_end:
clip_records: .import binary "build/geometry/clip-records.bin"
limb_remap: .import binary "build/geometry/limb-remap.bin"
static_end:
.assert "Movie does not overlap static data", MOVIE_ADDRESS >= static_end, true
* = MOVIE_ADDRESS "One source frame; benchmark may replace it at render_start"
movie: .import binary "build/native-geometry/initial-frame.bin"
movie_end:
.assert "Largest frame fits below I/O", movie_end <= $d000, true
.import source "build/native-geometry/selected-edge.asm"
