// Exact approved60-frame MickeyGIF + native SID3 sample-and-hold whistle.
// Direct front-buffer character deltas: no image re-rendering or screen copy.
// All screen data is precomputed; sample NMI and four-bit expansion retain
// the standalone component's behavior. Foreground work pumps between chunks.
.import source "config.asm"
.label buffer_a=$0200
.label buffer_b=$0300
.label boundary_count=$02
.label boundary_before=$03
.label generated_pages=$04
.label underruns=$05
.label finished=$06
.label next_buffer=$07
.label target_buffer=$08
.label source_ptr=$20
.label destination=$22
.label nmi_entry=$dc04
.macro read_movie_byte() {
    ldy #0
    lda (source_ptr),y
    inc source_ptr
    bne !ready+
    inc source_ptr+1
    pha
    jsr advance_movie_page
    pla
!ready:
}
BasicUpstart2(start)
*=$1000 "Combined AV runtime"
start:
    sei
    cld
    ldx #$ff
    txs
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
    sta $dc0e
    sta $dc0f
    sta $dd0e
    sta $dd0f
    sta $d011
    sta $d015
    sta $d01a
    sta $d020
    lda #$ff
    sta $d019
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
    lda #0
    ldx #24
!sid_clear:
    sta $d400,x
    dex
    bpl !sid_clear-
    ldx #6
!audio_state:
    sta $02,x
    dex
    bpl !audio_state-
    ldx #film_state_end-film_state-1
!film_state:
    sta film_state,x
    dex
    bpl !film_state-
    ldx #0
!clear:
    .for(var p=0;p<4;p++) {
        sta $0400+p*$100,x
        sta $0800+p*$100,x
        sta $d800+p*$100,x
    }
    inx
    bne !clear-
    ldx #0
!nmi_copy:
    lda nmi_image,x
    sta $80,x
    inx
    cpx #(nmi_end-nmi_common)
    bne !nmi_copy-
    lda #$40
    sta $dd0c
    lda #<nmi_entry
    sta $fffa
    lda #>nmi_entry
    sta $fffb
    lda #$4c
    sta $dc04
    lda #4
    sta front_screen_hi
    sta back_screen_hi
    lda #<keyframe_data
    sta source_ptr
    lda #>keyframe_data
    sta source_ptr+1
    jsr apply_screen_delta
    lda #<PACKED_START
    sta packed_read+1
    lda #>PACKED_START
    sta packed_read+2
    lda #>buffer_a
    sta target_buffer
    jsr fill_page
    lda #>buffer_b
    sta target_buffer
    jsr fill_page
    lda #>buffer_b
    sta next_buffer
    lda #1
    sta frame_present_count
    lda #0
    sta $d413
    lda #$f0
    sta $d414
    lda #1
    sta $d412
    lda #15
    sta $d418
    // Prime the same neutral held voltage and envelope as the native mixer.
    lda #128
    sta $d40f
    lda #9
    sta $d412
    lda #1
    sta $d412
    .fill 47,$ea
    lda #17
    sta $d412
    lda #1
    sta $d412
    lda #0
    sta $d40f
    ldy #32
!warm_outer:
    ldx #0
!warm_inner:
    dex
    bne !warm_inner-
    dey
    bne !warm_outer-
    lda #$9b
    sta $d011
    lda #0
    sta $dc05
    lda #125
    sta $dc06
    lda #0
    sta $dc07
    lda #125
    sta $dd04
    lda #0
    sta $dd05
    lda #$81
    sta $dd0d
    // Starting near an even rasterline keeps sample transfers off badlines.
    lda #$fe
!raster_wait:
    cmp $d012
    bne !raster_wait-
    lda #$11
sample_clock_start:
    sta $dd0e
    sta $dc0f
    jsr presented
    jmp main_loop
presented:
    nop
    rts
main_loop:
    lda film_frame
    cmp #FRAME_COUNT-1
    bne !next_frame+
    jmp wait_audio_end
!next_frame:
    clc
    adc #1
    sta next_frame
!deadline:
    jsr pump_audio
    jsr read_sample_epoch
    ldx next_frame
    lda sample_epoch_high
    cmp deadline_high,x
    bcc !deadline-
    bne !draw+
    lda sample_epoch_low
    cmp deadline_low,x
    bcc !deadline-
!draw:
    lda sample_epoch_low
    sta draw_start_sample_low
    lda sample_epoch_high
    sta draw_start_sample_high
    lda frame_pointer_low,x
    sta source_ptr
    lda frame_pointer_high,x
    sta source_ptr+1
prepare_start:
    jsr apply_screen_delta
prepared:
    nop
commit_start:
    jsr read_sample_epoch
    lda sample_epoch_low
    sta presented_sample_low
    lda sample_epoch_high
    sta presented_sample_high
    lda next_frame
    sta film_frame
    inc frame_present_count
commit_end:
    nop
    jsr presented
    jmp main_loop

wait_audio_end:
    jsr pump_audio
    lda finished
    beq wait_audio_end
playback_done:
    lda #0
    sta $d40f
    lda #$09
    sta $d412
done:
    .if(LOOP != 0) { jmp start } else { jmp done }

read_sample_epoch:
!again:
    lda boundary_count
    sta sample_epoch_high
    lda buffer_read+1
    sta sample_epoch_low
    lda boundary_count
    cmp sample_epoch_high
    bne !again-
    rts

pump_audio:
    lda finished
    bne !return+
    lda boundary_count
    cmp boundary_before
    beq !return+
    sta boundary_before
    lda generated_pages
    cmp #PAGE_COUNT
    beq !return+
    lda next_buffer
    sta target_buffer
    jsr fill_page
    lda boundary_count
    cmp boundary_before
    beq !return+
    inc underruns
!return:
    rts

advance_movie_page:
    lda source_ptr+1
    cmp #$70
    bne !return+
    lda #$79
    sta source_ptr+1
!return:
    rts

fill_page:
    lda target_buffer
    sta decoded_high+2
    sta decoded_low+2
    ldy #0
!decode:
packed_read:
    // Stable6510LAX; identical native sample values.
    .byte $af
    .word PACKED_START
    and #$f0
decoded_high:
    sta buffer_a,y
    iny
    lda low_lookup,x
decoded_low:
    sta buffer_a,y
    inc packed_read+1
    bne !source_ready+
    inc packed_read+2
    jsr advance_source_page
!source_ready:
    iny
    bne !decode-
    inc generated_pages
producer_done:
    rts


.import source "source-transitions.asm"
nmi_image:
.pseudopc $80 {
nmi_common:
first_latch:
    lda #$11
    sta $d412
    lda #$01
    sta $d412
    lda #$09
    sta $d412
buffer_read:
    lda buffer_a
    sta $d40f
    lda #$01
    sta $d412
sample_dispatch:
    jmp count_sample
count_sample:
    .byte $e6,<(buffer_read+1)
    bne nmi_return
consumer_activate:
    lda next_buffer
    .byte $85,<(buffer_read+2)
    eor #1
    sta next_buffer
    inc boundary_count
    lda boundary_count
    cmp #FULL_PAGES
    bne nmi_return
    lda #<count_final
    .byte $85,<(sample_dispatch+1)
    jmp nmi_return
count_final:
    .byte $e6,<(buffer_read+1)
    .byte $a5,<(buffer_read+1)
    cmp #FINAL_VALUES
    bne nmi_return
    lda #<emit_final
    .byte $85,<(sample_dispatch+1)
    jmp nmi_return
emit_final:
    // The last source value was emitted by this interrupt. The neutral guard
    // is prepared now, and one more whole sample period remains before stop.
    lda #<stop_sampling
    .byte $85,<(sample_dispatch+1)
    jmp nmi_return
stop_sampling:
    lda #0
    sta $dd0e
    sta $dc0f
    lda #$7f
    sta $dd0d
    lda $dd0d
    lda #1
    sta finished
nmi_return:
restore_a:
    lda #0
    jmp $dd0c
nmi_end:
}
.assert "The sample handler must fit its zero-page arena",nmi_end<=$100,true
apply_screen_delta:
    :read_movie_byte()
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
    lda #1
    sta command_budget
!command:
    dec command_budget
    bne !serviced+
    jsr service_movie_audio
!serviced:
    :read_movie_byte()
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
    clc
    adc #1
    sta literal_part
    lda #0
    sta literal_remainder
    // An indirect-Y copy may cross ordinary pages, but not the reserved
    // jitter pages. Split only at the physical$7000->$7900 movie gap.
    lda source_ptr+1
    cmp #$6f
    bne !bulk+
    lda source_ptr
    clc
    adc literal_part
    bcc !bulk+
    lda #0
    sec
    sbc source_ptr
    sta literal_first
    lda literal_part
    sec
    sbc literal_first
    sta literal_remainder
    lda literal_first
    sta literal_part
!bulk:
    jsr copy_literal_part
    lda literal_part
    cmp #32
    bcc !small+
    jsr service_movie_audio
!small:
    lda literal_remainder
    beq !command-
    sta literal_part
    lda #0
    sta literal_remainder
    jmp !bulk-
!done:
    rts

service_movie_audio:
    jsr pump_audio
    lda #4
    sta command_budget
    rts

copy_literal_part:
    ldy #0
    ldx literal_part
!byte:
    lda (source_ptr),y
    sta (destination),y
    iny
    dex
    bne !byte-
    tya
    clc
    adc source_ptr
    sta source_ptr
    bcc !source_ready+
    inc source_ptr+1
    jsr advance_movie_page
!source_ready:
    tya
    clc
    adc destination
    sta destination
    bcc !destination_ready+
    inc destination+1
!destination_ready:
    rts

// Four pages. Each has a uint16 group count; each group has a screen value,
// uint8(count-1), and that many uint8 positions within its 256-cell page.
apply_screen_groups:
    lda #0
    sta destination
    sta physical_page
!page:
    jsr pump_audio
    lda back_screen_hi
    clc
    adc physical_page
    sta destination+1
    :read_movie_byte()
    sta groups_left
    :read_movie_byte()
    sta groups_left+1
!group:
    jsr pump_audio
    lda groups_left
    ora groups_left+1
    beq !next_page+
    :read_movie_byte()
    sta plot_value
    :read_movie_byte()
    sta positions_left
    lda #32
    sta pump_budget
!position:
    :read_movie_byte()
    tay
    lda plot_value
    sta (destination),y
    dec pump_budget
    bne !pumped+
    jsr pump_audio
    lda #32
    sta pump_budget
!pumped:
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
    beq !all_pages+
    jmp !page-
!all_pages:
    rts

film_state:
film_frame: .byte 0
next_frame: .byte 0
front_screen_hi: .byte 0
back_screen_hi: .byte 0
frame_present_count: .byte 0
draw_start_sample_low: .byte 0
draw_start_sample_high: .byte 0
presented_sample_low: .byte 0
presented_sample_high: .byte 0
sample_epoch_low: .byte 0
sample_epoch_high: .byte 0
literal_part: .byte 0
literal_remainder: .byte 0
literal_first: .byte 0
command_budget: .byte 0
pump_budget: .byte 0
physical_page: .byte 0
plot_value: .byte 0
groups_left: .word 0
positions_left: .byte 0
film_state_end:
frame_pointer_low: .fill FRAME_COUNT,framePointers.get(i*2)
frame_pointer_high: .fill FRAME_COUNT,framePointers.get(i*2+1)
deadline_low: .fill FRAME_COUNT,frameDeadlines.get(i*2)
deadline_high: .fill FRAME_COUNT,frameDeadlines.get(i*2+1)
player_code_end:
.assert "AV runtime fits before encoded keyframe",player_code_end<=$1800,true
.import source "data.asm"
