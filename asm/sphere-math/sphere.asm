// Fixed-axis mathematical sphere: the 6510 selects every displayed screen code.
// Static geometry and font tables contain no screen frames or frame deltas.

#import "assets/constants.asm"

.label record_ptr = $02
.label probe_ptr = $04
.label valid_ptr = $06
.label screen_ptr = $08
.label scale_ptr = $0a
.label glyph_ptr = $0c
.label remaining = $0e
.label tile_flags = $10
.label tile_phase = $11
.label fraction = $12
.label u_parity = $13
.label edge_offset = $14
.label u_state = $15
.label polarity = $16
.label selected_glyph = $17
.label signature_lo = $18
.label signature_hi = $19
.label minimum_state = $1a

BasicUpstart2(start)

* = $2000 "Mathematical font"
font:
    .import binary "assets/font.bin"
.assert "Font must contain 256 glyphs", * - font, 2048

* = $3000 "Native sphere runtime"
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
    sta spin
    sta mode
    sta paused
    sta frame_counter
    sta frame_counter+1
    sta f1_held
    sta space_held
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

    // Select VIC bank $0000; font $2000 avoids the character-ROM window.
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #$ff
    sta $dc02
    sta $dc00
    lda #0
    sta $dc03

    ldx #0
!clear:
    lda #0
    .for (var page = 0; page < 4; page++) {
        sta $0400 + page*$100,x
        sta $0c00 + page*$100,x
    }
    lda #1
    .for (var page = 0; page < 4; page++) {
        sta $d800 + page*$100,x
    }
    inx
    bne !clear-

    lda #$04
    sta front_screen_hi
    lda #$0c
    sta back_screen_hi
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    lda #$1b
    sta $d011

main:
    jsr read_keyboard
render_start:
    lda #<records
    sta record_ptr
    lda #>records
    sta record_ptr+1
    lda #<probes
    sta probe_ptr
    lda #>probes
    sta probe_ptr+1
    lda #<valid_masks
    sta valid_ptr
    lda #>valid_masks
    sta valid_ptr+1
    lda #<SPHERE_TILE_COUNT
    sta remaining
    lda #>SPHERE_TILE_COUNT
    sta remaining+1

tile_loop:
    ldy #0
    lda (record_ptr),y
    sta screen_ptr
    iny
    lda (record_ptr),y
    clc
    adc back_screen_hi
    sta screen_ptr+1
    iny
    lda (record_ptr),y
    sta tile_flags
    and #1
    ora mode
    beq !analytic+
    jsr sparse_glyph
    jmp write_glyph
!analytic:
    jsr analytic_glyph
write_glyph:
    ldy #0
    sta (screen_ptr),y

    clc
    lda record_ptr
    adc #RECORD_SIZE
    sta record_ptr
    bcc !record_ok+
    inc record_ptr+1
!record_ok:
    clc
    lda probe_ptr
    adc #9
    sta probe_ptr
    bcc !probe_ok+
    inc probe_ptr+1
!probe_ok:
    clc
    lda valid_ptr
    adc #2
    sta valid_ptr
    bcc !valid_ok+
    inc valid_ptr+1
!valid_ok:
    lda remaining
    bne !decrement+
    dec remaining+1
!decrement:
    dec remaining
    lda remaining
    ora remaining+1
    beq render_end
    jmp tile_loop

render_end:
    // Complete the hidden buffer before waiting for PAL raster wrap to line 0.
    jsr wait_raster
    ldx front_screen_hi
    lda back_screen_hi
    sta front_screen_hi
    stx back_screen_hi
    cmp #$04
    beq !screen_0400+
    lda #$38
    bne !display+
!screen_0400:
    lda #$18
!display:
    sta $d018
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    // At this checkpoint front_screen_hi, mode and spin describe the visible frame.
    lda paused
    bne !no_spin+
    lda spin
    clc
    adc #SPHERE_PHASE_STEP
    and #127
    sta spin
!no_spin:
    jmp main

analytic_glyph:
    ldy #3
    lda (record_ptr),y
    clc
    adc spin
    and #127
    sta tile_phase
    and #63
    sta fraction
    lda tile_phase
    and #64
    beq !even+
    lda #1
!even:
    sta u_parity

    lda fraction
    cmp #32
    bcc !distance+
    eor #63
    clc
    adc #1
!distance:
    ldy #12
    cmp (record_ptr),y
    bcc u_boundary
    beq u_boundary
    ldy #8
    lda (record_ptr),y
    ldx u_parity
    beq !constant_done+
    tax
    lda inverse_table,x
!constant_done:
    rts

u_boundary:
    lda tile_flags
    and #2
    bne pair_boundary

    ldy #4
    lda (record_ptr),y
    tax
    lda scale_row_lo,x
    sta scale_ptr
    lda scale_row_hi,x
    clc
    adc #>scale_single
    sta scale_ptr+1
    ldy fraction
    lda (scale_ptr),y
    sta edge_offset

    // Single-table base is page aligned; the record supplies angle*25.
    ldy #5
    clc
    adc (record_ptr),y
    sta glyph_ptr
    iny
    lda (record_ptr),y
    adc #>single_table
    sta glyph_ptr+1
    ldy #0
    lda (glyph_ptr),y
    sta selected_glyph

    lda #0
    ldx fraction
    cpx #32
    bcs !center_zero+
    lda #1
!center_zero:
    eor u_parity
    ldy #11
    eor (record_ptr),y
    beq !single_done+
    ldx selected_glyph
    lda inverse_table,x
    rts
!single_done:
    lda selected_glyph
    rts

pair_boundary:
    ldy #4
    lda (record_ptr),y
    tax
    lda scale_row_lo,x
    sta scale_ptr
    lda scale_row_hi,x
    clc
    adc #>scale_pair
    sta scale_ptr+1
    ldy fraction
    lda (scale_ptr),y
    sta edge_offset
    lda tile_flags
    and #4
    beq !normal_ready+
    lda #8
    sec
    sbc edge_offset
    sta edge_offset
!normal_ready:
    ldy #7
    lda (record_ptr),y
    clc
    adc edge_offset
    sta u_state

    lda tile_flags
    and #4
    lsr
    lsr
    eor u_parity
    ldx fraction
    cpx #32
    bcs !pair_center_zero+
    eor #1
!pair_center_zero:
    ldy #11
    eor (record_ptr),y
    ldy #10
    eor (record_ptr),y
    sta polarity

    // The symmetric table uses precomputed row bases max*(max+1).
    ldy #9
    lda (record_ptr),y
    cmp u_state
    bcc !u_larger+
    tax
    lda u_state
    jmp !states_sorted+
!u_larger:
    sta minimum_state
    ldx u_state
    lda minimum_state
!states_sorted:
    asl
    clc
    adc polarity
    clc
    adc pair_row_lo,x
    sta glyph_ptr
    lda pair_row_hi,x
    adc #>xor_table
    sta glyph_ptr+1
    ldy #0
    lda (glyph_ptr),y
    rts

sparse_glyph:
    lda #0
    sta signature_lo
    sta signature_hi
    // Reverse traversal places probe p in signature bit p.
    ldy #8
!probe:
    lda (probe_ptr),y
    clc
    adc spin
    asl
    asl                             // Q6 checker parity is bit 6, now in carry.
    rol signature_lo
    rol signature_hi
    dey
    bpl !probe-
    ldy #0
    lda (valid_ptr),y
    and signature_lo
    tax
    iny
    lda (valid_ptr),y
    and signature_hi
    beq !lower_page+
    lda probe_lut+$100,x
    ldy tile_flags
    cpy #8                          // Assigned flag bits 0..3 make this the limb test.
    bcs clip_limb
    rts
!lower_page:
    lda probe_lut,x
    ldy tile_flags
    cpy #8
    bcs clip_limb
    rts

clip_limb:
    tax
    lda glyph_compact,x
    // Fallback records reuse angle-base fields for class*158, relative to the table.
    ldy #5
    clc
    adc (record_ptr),y
    sta glyph_ptr
    iny
    lda (record_ptr),y
    adc #>limb_remap
    sta glyph_ptr+1
    ldy #0
    lda (glyph_ptr),y
    rts

read_keyboard:
    lda #$fe
    sta $dc00
    lda $dc01
    and #$10
    bne !f1_up+
    lda f1_held
    bne !space+
    lda #1
    sta f1_held
    lda mode
    eor #1
    sta mode
    jmp !space+
!f1_up:
    lda #0
    sta f1_held
!space:
    lda #$7f
    sta $dc00
    lda $dc01
    and #$10
    bne !space_up+
    lda space_held
    bne !keyboard_done+
    lda #1
    sta space_held
    lda paused
    eor #1
    sta paused
    jmp !keyboard_done+
!space_up:
    lda #0
    sta space_held
!keyboard_done:
    lda #$ff
    sta $dc00
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

spin:               .byte 0
mode:               .byte 0
paused:             .byte 0
frame_counter:      .word 0
front_screen_hi:    .byte $04
back_screen_hi:     .byte $0c
f1_held:            .byte 0
space_held:         .byte 0

.assert "Runtime must fit below assets", * < $4000, true

* = $4000 "Static geometry and font lookup tables"
records:
    .import binary "assets/records.bin"
.assert "Geometry record length", * - records, SPHERE_TILE_COUNT * RECORD_SIZE
probes:
    .import binary "assets/probes.bin"
.assert "Probe record length", * - probes, SPHERE_TILE_COUNT * 9
valid_masks:
    .import binary "assets/valid.bin"
.assert "Validity record length", * - valid_masks, SPHERE_TILE_COUNT * 2
scale_row_lo:
    .import binary "assets/scale-lo.bin"
scale_row_hi:
    .import binary "assets/scale-hi.bin"
pair_row_lo:
    .import binary "assets/pair-lo.bin"
pair_row_hi:
    .import binary "assets/pair-hi.bin"
inverse_table:
    .import binary "assets/inverse.bin"

.align $100
scale_single:
    .import binary "assets/scale-single.bin"
.align $100
scale_pair:
    .import binary "assets/scale-pair.bin"
.align $100
single_table:
    .import binary "assets/single.bin"
.align $100
xor_table:
    .import binary "assets/xor.bin"
.align $100
probe_lut:
    .import binary "assets/probe-lut.bin"
.align $100
glyph_compact:
    .import binary "assets/glyph-compact.bin"
.assert "Glyph compact index length", * - glyph_compact, 256
.align $100
limb_remap:
    .import binary "assets/limb-remap.bin"
.assert "Safe limb remap length", * - limb_remap, 9954
assets_end:
.assert "Static data must fit below I/O", assets_end <= $d000, true
