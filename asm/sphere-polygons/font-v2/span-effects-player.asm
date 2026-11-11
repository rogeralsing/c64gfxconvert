// Direct independent X,length,raw-character spans. Two output screens only.
BasicUpstart2(start)
.label source_ptr=$02
.label destination=$04
.label cache_write=$06
.label span_x=$08
.label span_left=$09
.label column=$0a
.label plot_value=$0b
.label source_age=$0c
.macro read_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !ready+
    inc source_ptr+1
!ready:
}
*=$1000 "Direct raw-span effects player"
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
    sta mode
    sta next_mode
    sta film_frame
    sta film_serial
    sta film_serial+1
    sta phase
    sta mode_due
    sta mode_started_field
    sta mode_started_field+1
    lda #$0b
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
    jsr reset_mode_clock
    lda #2
    sta frame_wait_fields
    jsr wait_raster_boundary
    lda #$9b
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
cache_start:
    jsr build_cache
cache_end:
    nop
render_start:
    jsr render_rows
render_end:
    nop
!wait:
    jsr wait_field
    lda next_mode
    cmp mode
    beq !normal_wait+
    lda mode_due
    beq !wait-
    jmp commit_start
!normal_wait:
    lda frame_wait_fields
    bne !wait-
commit_start:
    sei
    lda next_mode
    cmp mode
    beq !same_mode+
    sta mode
    jsr reset_mode_clock
    lda field_counter
    sta mode_started_field
    lda field_counter+1
    sta mode_started_field+1
!same_mode:
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
    lda next_phase
    sta phase
    lda #2
    sta frame_wait_fields
commit_end:
    nop
    cli
    jmp presented

select_next:
    lda mode
    sta next_mode
    lda mode_fields_left+1
    bne !same+
    lda mode_fields_left
    cmp #6
    bcs !same+
    inc next_mode
    lda next_mode
    cmp #3
    bcc !same+
    lda #0
    sta next_mode
!same:
    lda film_frame
    clc
    adc #1
    cmp #97
    bcc !pose+
    lda #1
!pose:
    sta next_film_frame
    cmp #96
    bne !phase+
    lda #0
!phase:
    sta next_phase
    lda film_serial
    clc
    adc #1
    sta next_serial
    lda film_serial+1
    adc #0
    sta next_serial+1
    rts
reset_mode_clock:
    lda #<501
    sta mode_fields_left
    lda #>501
    sta mode_fields_left+1
    lda #0
    sta mode_due
    rts

// Reuse one500-byte pool: normal1table, wave10tables, checker2tables.
// Table slots store interleaved absolute row-record pointers (25x2bytes).
build_cache:
    lda #1
    sta cache_table_count
    lda next_mode
    cmp #1
    bne !checker+
    lda #10
    sta cache_table_count
!checker:
    cmp #2
    bne !start+
    lda #2
    sta cache_table_count
!start:
    lda #0
    sta cache_slot
!table:
    lda cache_slot
    sta source_age
    lda next_mode
    cmp #2
    bne !age+
    lda cache_slot
    beq !age+
    lda #48
    sta source_age
!age:
    jsr age_to_source_frame
    ldx cache_slot
    sta cache_frame_ids,x
    tax
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    ldx cache_slot
    lda cache_pointer_low,x
    sta cache_write
    lda cache_pointer_high,x
    sta cache_write+1
    lda #25
    sta cache_rows_left
!row:
    ldy #0
    lda source_ptr
    sta (cache_write),y
    iny
    lda source_ptr+1
    sta (cache_write),y
    lda (source_ptr),y
    clc
    adc #2
    clc
    adc source_ptr
    sta source_ptr
    bcc !source_ready+
    inc source_ptr+1
!source_ready:
    lda cache_write
    clc
    adc #2
    sta cache_write
    bcc !cache_ready+
    inc cache_write+1
!cache_ready:
    dec cache_rows_left
    bne !row-
    inc cache_slot
    lda cache_slot
    cmp cache_table_count
    bne !table-
    rts

age_to_source_frame:
    lda next_serial+1
    bne !positive+
    lda next_serial
    cmp source_age
    beq !blank+
    bcc !blank+
!positive:
    lda next_film_frame
    sec
    sbc source_age
    bcs !nonnegative+
    clc
    adc #96
    rts
!nonnegative:
    bne !done+
    lda #96
!done:
    rts
!blank:
    lda #0
    rts

render_rows:
    lda #0
    sta physical_row
!row:
    ldx physical_row
    lda row_offset_low,x
    sta destination
    lda row_offset_high,x
    clc
    adc back_screen_hi
    sta destination+1
    lda #0
    sta selected_cache_slot
    sta mask_mode
    lda next_mode
    cmp #1
    bne !not_wave+
    lda wave_pointer_low,x
    sta wave_load+1
    lda wave_pointer_high,x
    sta wave_load+2
    ldx next_phase
wave_load:
    lda wave_ages,x
    sta selected_cache_slot
!not_wave:
    lda next_mode
    cmp #2
    bne !draw_a+
    lda #1
    sta mask_mode
!draw_a:
    jsr setup_clip
    jsr draw_cached_span
    lda next_mode
    cmp #2
    bne !next_row+
    lda #1
    sta selected_cache_slot
    lda #2
    sta mask_mode
    jsr setup_clip
    jsr draw_cached_span
!next_row:
    inc physical_row
    lda physical_row
    cmp #25
    bne !row-
    rts

draw_cached_span:
    ldx selected_cache_slot
    lda cache_pointer_low,x
    sta cache_write
    lda cache_pointer_high,x
    sta cache_write+1
    lda physical_row
    asl
    tay
    lda (cache_write),y
    sta source_ptr
    iny
    lda (cache_write),y
    sta source_ptr+1
span_start:
    :read_byte()
    sta column
    :read_byte()
    sta span_left
    lda span_left
    beq span_end
!copy:
    :read_byte()
    jsr plot_dispatch
    dec span_left
    bne !copy-
span_end:
    nop
    rts
setup_clip:
    lda mask_mode
    bne !checker+
    lda #<plot_all
    sta plot_dispatch+1
    lda #>plot_all
    sta plot_dispatch+2
    rts
!checker:
    lda #<plot_clipped
    sta plot_dispatch+1
    lda #>plot_clipped
    sta plot_dispatch+2
    lda physical_row
    lsr
    lsr
    and #1
    sta clip_parity
    lda mask_mode
    cmp #1
    beq !parity+
    lda clip_parity
    eor #1
    sta clip_parity
!parity:
    lda clip_parity
    beq !even+
    lda #<clip_odd
    ldx #>clip_odd
    jmp !patch+
!even:
    lda #<clip_even
    ldx #>clip_even
!patch:
    sta clip_load+1
    stx clip_load+2
    rts

plot_dispatch:
    jmp plot_all
plot_all:
    ldy column
packet_store_all:
    sta (destination),y
    inc column
    rts
plot_clipped:
    sta plot_value
    ldy column
clip_load:
    lda clip_even,y
    beq clip_reject
    lda plot_value
packet_store:
    sta (destination),y
clip_reject:
    inc column
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
    bne !field+
    inc field_counter+1
!field:
    lda frame_wait_fields
    beq !mode+
    dec frame_wait_fields
!mode:
    lda mode_due
    bne field_complete
    lda mode_fields_left
    bne !decrement+
    dec mode_fields_left+1
!decrement:
    dec mode_fields_left
    lda mode_fields_left
    ora mode_fields_left+1
    bne field_complete
    lda #1
    sta mode_due
field_complete:
    nop
    pla
irq_return:
    rti
interrupt_return:
    rti

mode: .byte 0
next_mode: .byte 0
film_frame: .byte 0
next_film_frame: .byte 0
film_serial: .word 0
next_serial: .word 0
phase: .byte 0
next_phase: .byte 0
field_counter: .word 0
mode_started_field: .word 0
mode_fields_left: .word 501
mode_due: .byte 0
frame_wait_fields: .byte 2
front_screen_hi: .byte $48
back_screen_hi: .byte $4c
physical_row: .byte 0
mask_mode: .byte 0
clip_parity: .byte 0
cache_slot: .byte 0
cache_table_count: .byte 0
cache_rows_left: .byte 0
selected_cache_slot: .byte 0
cache_frame_ids: .fill 10, 0
row_cache: .fill 500, 0
cache_pointer_low: .fill 10, <(row_cache+i*50)
cache_pointer_high: .fill 10, >(row_cache+i*50)
frame_pointer_low: .fill 97, <($5000+(indexData.get(i*2)&$ff)+(indexData.get(i*2+1)&$ff)*256)
frame_pointer_high: .fill 97, >($5000+(indexData.get(i*2)&$ff)+(indexData.get(i*2+1)&$ff)*256)
row_offset_low: .fill 25, <(i*40)
row_offset_high: .fill 25, >(i*40)
clip_even: .fill 40, (floor(i/4)&1)==0 ? 1 : 0
clip_odd: .fill 40, (floor(i/4)&1)==1 ? 1 : 0
wave_pointer_low: .fill 25, <(wave_ages+i*96)
wave_pointer_high: .fill 25, >(wave_ages+i*96)
wave_ages: .fill waveData.getSize(), waveData.get(i)
player_code_end:
.assert "Code and wave LUT below font", player_code_end <= $4000, true
*=$4000 "Locked unchanged font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Full font", *-font, 2048
*=$5000 "Independent raw X,length,chars rows"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Spans below I/O", animation_end <= $d000, true
