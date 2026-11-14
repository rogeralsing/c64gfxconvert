// Monochrome 256-glyph hires movie. Packets contain only screen deltas.
BasicUpstart2(start)
.label source_ptr=$02
.label destination=$04

.macro read_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !ready+
    inc source_ptr+1
!ready:
}

*=$1000 "Monochrome movie player"
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
    sta $d011
    sta $d01a
    sta $d015
    sta $d020
    lda #1
    sta $d021
    lda #8
    sta $d016
    lda #$18
    sta $d018
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    ldx #0
!bootstrap:
    .for(var page=0;page<4;page++) {
        lda initialScreenData+page*$100,x
        sta $0400+page*$100,x
        sta $0800+page*$100,x
    }
    inx
    bne !bootstrap-
    // Fixed black foreground: this is the only ColorRAM write loop.
    lda #0
    ldx #0
color_ram_init:
    .for(var page=0;page<4;page++) {
        sta $d800+page*$100,x
    }
    inx
    bne color_ram_init
color_ram_init_end:
    lda #<interrupt_return
    sta $fffa
    lda #>interrupt_return
    sta $fffb
    lda #<field_irq
    sta $fffe
    lda #>field_irq
    sta $ffff
    lda #0
    sta $d012
    lda #holdFields
    sta fields_left
    lda #1
    sta $d019
    sta $d01a
    // Enable the completed bootstrap image before the next visible field.
!high:
    bit $d011
    bpl !high-
!low:
    bit $d011
    bmi !low-
    lda #$9b
    sta $d011
    // The disabled display used raster compare 0. Clear that pending match
    // after switching the compare high bit to 256, before accepting IRQs.
    lda #1
    sta $d019
    cli

presented:
    nop
prepare_start:
    lda film_frame
    clc
    adc #1
    cmp #frameCount
    bcc !next+
    lda #0
!next:
    sta next_frame
    jsr copy_front_screen
    ldx next_frame
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
    jsr apply_screen_delta
prepared:
    nop
!wait:
    lda frame_due
    beq !wait-

commit_start:
    sei
    // Flip the completed matrix below the visible area. No colors change.
    lda back_screen_hi
    sta front_screen_hi
    cmp #4
    beq !screen0+
    lda #$28
    bne !screen+
!screen0:
    lda #$18
!screen:
    sta $d018
    lda back_screen_hi
    eor #$0c
    sta back_screen_hi
    lda next_frame
    sta film_frame
    lda #holdFields
    sta fields_left
    lda #0
    sta frame_due
commit_end:
    nop
    cli
    jmp presented

copy_front_screen:
    lda front_screen_hi
    sta screen_load0+2
    clc
    adc #1
    sta screen_load1+2
    adc #1
    sta screen_load2+2
    adc #1
    sta screen_load3+2
    lda back_screen_hi
    sta screen_store0+2
    clc
    adc #1
    sta screen_store1+2
    adc #1
    sta screen_store2+2
    adc #1
    sta screen_store3+2
    ldx #0
!copy:
screen_load0: lda $0400,x
screen_store0: sta $0800,x
screen_load1: lda $0500,x
screen_store1: sta $0900,x
screen_load2: lda $0600,x
screen_store2: sta $0a00,x
screen_load3: lda $0700,x
screen_store3: sta $0b00,x
    inx
    bne !copy-
    rts

apply_screen_delta:
    :read_byte()
    cmp #0
    bne apply_screen_cursor
    jmp apply_screen_groups

// Flat screen cursor: zero terminates, 1..127 skip unchanged cells, and
// 128..255 copy the following 1..128 raw bytes. The converter chooses this
// or page groups for each frame using the exact stored byte count.
apply_screen_cursor:
    lda #0
    sta destination
    lda back_screen_hi
    sta destination+1
!command:
    :read_byte()
    cmp #0
    beq !done+
    bmi !copy+
    clc
    adc destination
    sta destination
    bcc !command-
    inc destination+1
    jmp !command-
!copy:
    and #127
    sta positions_left
!literal:
    :read_byte()
    sta (destination),y
    inc destination
    bne !advanced+
    inc destination+1
!advanced:
    lda positions_left
    beq !command-
    dec positions_left
    jmp !literal-
!done:
    rts

// Four pages. Each has a uint16 group count; each group has a screen value,
// uint8(count-1), and that many uint8 positions within its 256-cell page.
apply_screen_groups:
    lda #0
    sta destination
    sta physical_page
!page:
    lda back_screen_hi
    clc
    adc physical_page
    sta destination+1
    :read_byte()
    sta groups_left
    :read_byte()
    sta groups_left+1
!group:
    lda groups_left
    ora groups_left+1
    beq !next_page+
    :read_byte()
    sta plot_value
    :read_byte()
    sta positions_left
!position:
    :read_byte()
    tay
    lda plot_value
    sta (destination),y
    lda positions_left
    beq !next_group+
    dec positions_left
    jmp !position-
!next_group:
    lda groups_left
    bne !decrement+
    dec groups_left+1
!decrement:
    dec groups_left
    jmp !group-
!next_page:
    inc physical_page
    lda physical_page
    cmp #4
    bne !page-
    rts

field_irq:
    pha
    lda #1
    sta $d019
    inc field_counter
    bne !counter+
    inc field_counter+1
!counter:
    lda frame_due
    bne field_complete
    dec fields_left
    bne field_complete
    lda #1
    sta frame_due
field_complete:
    nop
    pla
    rti
interrupt_return:
    rti

film_frame: .byte 0
next_frame: .byte 0
front_screen_hi: .byte $04
back_screen_hi: .byte $08
fields_left: .byte holdFields
frame_due: .byte 0
field_counter: .word 0
physical_page: .byte 0
plot_value: .byte 0
groups_left: .word 0
positions_left: .byte 0
frame_pointer_low: .fill frameCount, framePointers.get(i*2)
frame_pointer_high: .fill frameCount, framePointers.get(i*2+1)
player_code_end:
.assert "Movie player below bootstrap data", player_code_end <= $1800, true

*=$1800 "Bootstrap character screen"
initialScreenData: .fill initialScreen.getSize(),initialScreen.get(i)
*=$2000 "Fixed 256-glyph hires font"
font: .fill fontData.getSize(),fontData.get(i)
font_end:
.assert "Hires font occupies exactly $2000-$27ff", font_end == $2800, true
*=$2800 "Cyclic movie deltas"
movie_data: .fill movieData.getSize(),movieData.get(i)
movie_end:
.assert "Movie load avoids CPU I/O", movie_end <= $d000, true
