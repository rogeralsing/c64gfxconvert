// GD64: precomputed geometric probe-mask deltas, live fixed-font dirty resolve.
BasicUpstart2(start)
#import "build/abi.asm"
.label source_ptr = $40
.label frame_ptr = $42
.label next_frame_ptr = $44
.label destination_ptr = $46
.label screen_ptr = $48
.label class_ptr = $4a
.label remap_ptr = $4c
.label packet_left = $4e
.label packet_value = $4f
.label chosen_glyph = $50
.label saved_y = $51
.label payload_length = $52
.label initial_faces = $54
.label queue_count = $55
.label queue_cell_lo = $1400
.label queue_cell_hi = $1480
.label queue_glyph = $1500
.var movieData = LoadBinary("build/geometry.gd64")
.assert "GD64 version", movieData.get(4), 1
.assert "GD64 frames", movieData.get(5), 64
.assert "GD64 probes", movieData.get(6), 8
.assert "GD64 disjoint endpoint flag", movieData.get(7), 1

* = $2000 "Original mathematical font"
font: .import binary "build/assets/font.bin"
* = $3000 "GD64 geometry-mask delta player"
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
        sta coverage+page*$100,x
        sta $0400+page*$100,x
    }
    lda #1
    .for(var page=0;page<4;page++){sta $d800+page*$100,x}
    inx
    bne !clear-
    lda #4
    sta front_screen_hi
    sta back_screen_hi
    lda #$18
    sta $d018
    lda #8
    sta $d016
    lda #<initial_geometry
    sta source_ptr
    lda #>initial_geometry
    sta source_ptr+1
    jsr initialize_geometry
    jsr reset_pointers
!initial_resolve:
    ldy #0
    lda (destination_ptr),y
    jsr resolve_mask
    lda #1
    sta packet_left
    jsr advance_pointers
    lda destination_ptr
    cmp #$e8
    bne !initial_resolve-
    lda destination_ptr+1
    cmp #$13
    bne !initial_resolve-
    lda #<geometry_deltas
    sta frame_ptr
    lda #>geometry_deltas
    sta frame_ptr+1
    lda #1
    sta queue_enabled
    sta target_update_index
    jsr wait_boundary
    lda #$1b
    sta $d011

render_start:
compute_start:
    lda #0
    sta queue_count
    jsr parse_frame
    jsr reset_pointers
    jsr decode_delta
    lda target_update_index
    beq !restart+
    lda next_frame_ptr
    sta frame_ptr
    lda next_frame_ptr+1
    sta frame_ptr+1
    jmp compute_end
!restart:
    lda #<geometry_deltas
    sta frame_ptr
    lda #>geometry_deltas
    sta frame_ptr+1
compute_end:
    nop
render_end:
wait_start:
    jsr wait_boundary
frame_boundary:
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
flush_start:
    jsr flush_queue
flush_end:
    nop
    lda target_update_index
    sta frame_index
    inc target_update_index
    lda target_update_index
    cmp #64
    bne !next+
    lda #0
    sta target_update_index
!next:
    jmp render_start

initialize_geometry:
    jsr read_source
    sta initial_faces
!face:
    jsr read_source
    sta raster_sample
    jsr read_source
    clc
    adc raster_sample
    sta raster_sample_end
    ldx raster_sample
!sample:
    jsr read_source
    sta span_left,x
    jsr read_source
    sta span_right,x
    inx
    cpx raster_sample_end
    bcc !sample-
    jsr raster_fill_span
    dec initial_faces
    bne !face-
    rts

reset_pointers:
    lda #0
    sta destination_ptr
    sta screen_ptr
    sta class_ptr
    lda #$10
    sta destination_ptr+1
    lda #4
    sta screen_ptr+1
    lda #>clip_cell_classes
    sta class_ptr+1
    rts

advance_pointers:
    clc
    lda destination_ptr
    adc packet_left
    sta destination_ptr
    sta screen_ptr
    sta class_ptr
    bcc !done+
    inc destination_ptr+1
    inc screen_ptr+1
    inc class_ptr+1
!done:
    rts

parse_frame:
    ldy #0
    lda (frame_ptr),y
    sta payload_length
    iny
    lda (frame_ptr),y
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
    pha
    and #63
    clc
    adc #1
    sta packet_left
    pla
    and #192
    beq !advance+
    cmp #64
    beq !literal+
    cmp #128
    beq !repeat+
    jmp invalid_movie
!literal:
    ldy #0
!copy:
    lda (source_ptr),y
    jsr apply_mask
    iny
    cpy packet_left
    bne !copy-
    clc
    lda source_ptr
    adc packet_left
    sta source_ptr
    bcc !advance+
    inc source_ptr+1
    jmp !advance+
!repeat:
    jsr read_source
    sta packet_value
    ldy #0
!copy:
    lda packet_value
    jsr apply_mask
    iny
    cpy packet_left
    bne !copy-
!advance:
    jsr advance_pointers
    lda source_ptr
    cmp next_frame_ptr
    bne !packet-
    lda source_ptr+1
    cmp next_frame_ptr+1
    bne !packet-
    lda destination_ptr
    cmp #$e8
    beq !low_ok+
    jmp invalid_movie
!low_ok:
    lda destination_ptr+1
    cmp #$13
    beq !high_ok+
    jmp invalid_movie
!high_ok:
    rts

apply_mask:
    cmp #0
    beq !done+
    eor (destination_ptr),y
    sta (destination_ptr),y
resolve_mask:
    tax
    lda glyph_lut,x
    sta chosen_glyph
    lda (class_ptr),y
    beq !plain+
    tax
    lda clip_row_lo,x
    sta remap_ptr
    lda clip_row_hi,x
    sta remap_ptr+1
    sty saved_y
    ldx chosen_glyph
    lda glyph_compact,x
    tay
    lda (remap_ptr),y
    ldy saved_y
    jmp !store+
!plain:
    lda chosen_glyph
!store:
    ldx queue_enabled
    beq !initial+
    sta chosen_glyph
    ldx queue_count
    cpx #128
    bcc !space+
    jmp invalid_movie
!space:
    tya
    clc
    adc screen_ptr
    sta queue_cell_lo,x
    lda screen_ptr+1
    adc #0
    sta queue_cell_hi,x
    lda chosen_glyph
    sta queue_glyph,x
    inc queue_count
    rts
!initial:
    sta (screen_ptr),y
!done:
    rts

read_source:
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !done+
    inc source_ptr+1
!done:
    rts

flush_queue:
    ldx #0
    cpx queue_count
    beq !done+
    ldy #0
!cell:
    lda queue_cell_lo,x
    sta remap_ptr
    lda queue_cell_hi,x
    sta remap_ptr+1
    lda queue_glyph,x
literal_store:
repeat_store:
screen_store:
    sta (remap_ptr),y
    inx
    cpx queue_count
    bcc !cell-
!done:
    rts

wait_raster:
wait_boundary:
!low:
    bit $d011
    bmi !low-
!high:
    bit $d011
    bpl !high-
    rts
invalid_movie:
    brk
    jmp invalid_movie
interrupt_return:
    rti
frame_index: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 4
queue_enabled: .byte 0
target_update_index: .byte 1

#import "build/fill.asm"
delta_code_end:
.assert "Code below assets", delta_code_end <= $4000, true
.align $100
glyph_lut: .import binary "build/assets/glyph-lut.bin"
glyph_compact: .import binary "build/assets/glyph-compact.bin"
limb_remap: .import binary "build/assets/limb-remap.bin"
.align $100
clip_cell_classes: .import binary "build/assets/clip-cell-classes.bin"
clip_row_lo:
    .byte 0
    .for(var i=0;i<60;i++){.byte <(limb_remap+i*148)}
clip_row_hi:
    .byte 0
    .for(var i=0;i<60;i++){.byte >(limb_remap+i*148)}
sample_row_lo: .import binary "build/assets/sample-row-lo.bin"
sample_row_hi: .import binary "build/assets/sample-row-hi.bin"
left_masks: .import binary "build/assets/left-masks.bin"
right_masks: .import binary "build/assets/right-masks.bin"
lookup_end:
animation:
    .import binary "build/geometry.gd64"
animation_end:
.label initial_geometry = animation+12
.label geometry_deltas = initial_geometry+movieData.get(8)+256*movieData.get(9)
.assert "All data below I/O", animation_end <= $d000, true
