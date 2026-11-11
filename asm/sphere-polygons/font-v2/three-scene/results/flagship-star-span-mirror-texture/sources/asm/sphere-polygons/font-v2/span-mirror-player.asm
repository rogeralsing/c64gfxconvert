// Four mirrored quadrants from direct raw spans; locked font remains unchanged.
BasicUpstart2(start)
.label source_ptr=$02
.label tl_destination=$04
.label tr_destination=$06
.label bl_destination=$08
.label br_destination=$0a
.label column=$0c
.label span_left=$0d
.label next_row_ptr=$0e
.label destination=tl_destination
.macro read_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !ready+
    inc source_ptr+1
!ready:
}
*=$1000 "Direct raw-span mirror player"
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
    sta field_counter
    sta field_counter+1
    sta film_frame
    sta film_serial
    sta film_serial+1
    lda #$0f
    sta $d011
    lda #<interrupt_return
    sta $fffa
    lda #>interrupt_return
    sta $fffb
    lda #<field_irq
    sta $fffe
    lda #>field_irq
    sta $ffff
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    ldx #0
!clear:
    lda #0
    .for(var p=0;p<8;p++) { sta $4800+p*$100,x }
    lda #1
    .for(var p=0;p<4;p++) { sta $d800+p*$100,x }
    inx
    bne !clear-
    lda #$48
    sta front_screen_hi
    lda #$4c
    sta back_screen_hi
    lda #$20
    sta $d018
    lda #8
    sta $d016
    lda #2
    sta frame_wait_fields
    jsr wait_raster_boundary
    lda #$9f
    sta $d011
    lda #0
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    cli
    jmp presented
presented:
    nop
prepare_start:
    jsr select_next
clear_start:
    jsr clear_back
clear_end:
    nop
render_start:
    jsr render_quadrants
render_end:
    nop
!wait:
    jsr wait_field
    lda frame_wait_fields
    bne !wait-
commit_start:
    sei
    lda front_screen_hi
    pha
    lda back_screen_hi
    sta front_screen_hi
    cmp #$48
    beq !screen0+
    lda #$30
    bne !d018+
!screen0:
    lda #$20
!d018:
    sta $d018
    pla
    sta back_screen_hi
    lda next_film_frame
    sta film_frame
    lda next_serial
    sta film_serial
    lda next_serial+1
    sta film_serial+1
    lda #2
    sta frame_wait_fields
commit_end:
    nop
    cli
    jmp presented
select_next:
    lda film_frame
    clc
    adc #1
    cmp #97
    bcc !pose+
    lda #1
!pose:
    sta next_film_frame
    lda film_serial
    clc
    adc #1
    sta next_serial
    lda film_serial+1
    adc #0
    sta next_serial+1
    rts

render_quadrants:
    ldx next_film_frame
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    lda #0
    sta physical_row
!row:
    ldx physical_row
    lda top_offset_low,x
    sta tl_destination
    sta tr_destination
    lda top_offset_high,x
    clc
    adc back_screen_hi
    sta tl_destination+1
    sta tr_destination+1
    lda bottom_offset_low,x
    sta bl_destination
    sta br_destination
    lda bottom_offset_high,x
    clc
    adc back_screen_hi
    sta bl_destination+1
    sta br_destination+1
span_start:
    :read_byte()
    sta column
    :read_byte()
    sta span_left
    // Save the next full source-row header before clipping raw data to TL.
    clc
    adc source_ptr
    sta next_row_ptr
    lda source_ptr+1
    adc #0
    sta next_row_ptr+1
    lda column
    cmp #20
    bcs !next_row+
    lda #20
    sec
    sbc column
    cmp span_left
    bcs !length_ready+
    sta span_left
!length_ready:
    lda span_left
    beq !next_row+
!glyph:
    :read_byte()
    tax
    ldy column
    txa
store_tl:
    sta (tl_destination),y
    lda v_lut,x
store_bl:
    sta (bl_destination),y
    lda h_lut,x
    tax
    lda mirror_column,y
    tay
    txa
store_tr:
    sta (tr_destination),y
    lda v_lut,x
store_br:
    sta (br_destination),y
    inc column
    dec span_left
    bne !glyph-
!next_row:
span_end:
    nop
    lda next_row_ptr
    sta source_ptr
    lda next_row_ptr+1
    sta source_ptr+1
    inc physical_row
    lda physical_row
    cmp #12
    beq !done+
    jmp !row-
!done:
    rts
clear_back:
    lda #0
    sta destination
    lda back_screen_hi
    sta destination+1
    ldx #4
    ldy #0
    lda #0
!clear:
    sta (destination),y
    iny
    bne !clear-
    inc destination+1
    dex
    bne !clear-
    rts

wait_field:
    lda field_counter
!wait:
    cmp field_counter
    beq !wait-
    rts
wait_raster_boundary:
!low:
    bit $d011
    bmi !low-
!high:
    bit $d011
    bpl !high-
    rts

field_irq:
    pha
    lda #1
    sta $d019
    inc field_counter
    bne !counter+
    inc field_counter+1
!counter:
    lda frame_wait_fields
    beq field_complete
    dec frame_wait_fields
field_complete:
    nop
    pla
irq_return:
    rti
interrupt_return:
    rti
film_frame: .byte 0
next_film_frame: .byte 0
film_serial: .word 0
next_serial: .word 0
field_counter: .word 0
frame_wait_fields: .byte 2
front_screen_hi: .byte $48
back_screen_hi: .byte $4c
physical_row: .byte 0
frame_pointer_low: .fill 97, <($5000+(indexData.get(i*2)&$ff)+(indexData.get(i*2+1)&$ff)*256)
frame_pointer_high: .fill 97, >($5000+(indexData.get(i*2)&$ff)+(indexData.get(i*2+1)&$ff)*256)
top_offset_low: .fill 12, <(i*40)
top_offset_high: .fill 12, >(i*40)
bottom_offset_low: .fill 12, <((23-i)*40)
bottom_offset_high: .fill 12, >((23-i)*40)
mirror_column: .fill 20, 39-i
.align $100
h_lut: .fill 256, hData.get(i)
v_lut: .fill 256, vData.get(i)
player_code_end:
.assert "Code and twoLUTs belowfont", player_code_end <= $4000, true
*=$4000 "Locked unchanged font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Fullfont", *-font, 2048
*=$5000 "Unchanged independent rawspanfilm"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Film belowI/O", animation_end <= $d000, true
