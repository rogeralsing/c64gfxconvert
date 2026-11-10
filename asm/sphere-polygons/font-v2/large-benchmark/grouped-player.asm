// Four-page character delta. Each page contains groupCount,singleCount,
// groups [glyph,count,offsets...] and singles [offset,glyph...]. Grouping
// changes write order within a page; actual PAL scanout must prove its safety.
BasicUpstart2(start)

.label source_ptr = $02
.label groups_left = $04
.label singles_left = $05
.label offsets_left = $06
.label group_glyph = $07

.macro next_source_byte() {
    iny
    bne !same_source_page+
    inc source_ptr+1
!same_source_page:
}

* = $1000 "Grouped-page character delta"
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
!initialize:
    lda #1
    .for (var page=0; page<4; page++) { sta $d800+page*$100,x }
    .for (var page=0; page<3; page++) {
        lda initial_screen+page*$100,x
        sta $0400+page*$100,x
    }
    inx
    bne !initialize-
    ldx #0
!initial_tail:
    lda initial_screen+$300,x
    sta $0700,x
    inx
    cpx #232
    bne !initial_tail-
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    jsr wait_boundary
    lda #$1b
    sta $d011
    jmp report_after_scan

render_start:
    ldx frame_index
    lda patch_pointer_low,x
    sta source_ptr
    lda patch_pointer_high,x
    sta source_ptr+1
    jsr decode_grouped
render_end:
    nop
copy_start:
    nop
copy_end:
    inc frame_index
report_after_scan:
    jsr wait_boundary
    inc frame_counter
    bne frame_done
    inc frame_counter+1
frame_done:
    lda frame_index
    cmp #PREVIEW_FRAME_COUNT-1
    beq stopped
    jmp render_start
stopped:
    jmp stopped

decode_grouped:
    ldy #0
    .for (var page=0; page<4; page++) {
        lda (source_ptr),y
        sta groups_left
        :next_source_byte()
        lda (source_ptr),y
        sta singles_left
        :next_source_byte()
        lda groups_left
        beq !groups_done+
    !group:
        lda (source_ptr),y
        sta group_glyph
        :next_source_byte()
        lda (source_ptr),y
        sta offsets_left
        :next_source_byte()
    !offset:
        lda (source_ptr),y
        tax
        lda group_glyph
        sta $0400+page*$100,x
        :next_source_byte()
        dec offsets_left
        bne !offset-
        dec groups_left
        bne !group-
    !groups_done:
        lda singles_left
        beq !page_done+
    !single:
        lda (source_ptr),y
        tax
        :next_source_byte()
        lda (source_ptr),y
        sta $0400+page*$100,x
        :next_source_byte()
        dec singles_left
        bne !single-
    !page_done:
    }
    rts

wait_boundary:
!leave_high:
    bit $d011
    bmi !leave_high-
!enter_high:
    bit $d011
    bpl !enter_high-
    rts
interrupt_return:
    rti

frame_index: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 4
patch_pointer_low:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2)
patch_pointer_high:
    .fill PREVIEW_FRAME_COUNT, pointerData.get(i*2+1)
player_code_end:
.assert "Code and all frame pointers fit below font", player_code_end <= $2000, true

* = $2000 "Immutable 256-character average font"
font: .fill fontData.getSize(), fontData.get(i)
.assert "Font bytes", *-font, 2048

* = $2800 "Exact initial character screen"
initial_screen: .fill initialData.getSize(), initialData.get(i)
.assert "Initial screen bytes", *-initial_screen, 1000

* = $3000 "Grouped-page character changes"
animation: .fill movieData.getSize(), movieData.get(i)
animation_end:
.assert "Movie stays below I/O", animation_end <= $d000, true
