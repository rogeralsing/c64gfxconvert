// Live polygon projection with a coverage-indexed OR font on a PAL C64.
#import "build/assets/constants.asm"
BasicUpstart2(start)

* = $2000 "Fixed mathematical character set"
font:
    .import binary "build/assets/font.bin"
.assert "Fixed font size", *-font, 2048

* = $3000 "Polygon character renderer"
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
    sta model
    sta angle_yaw
    sta angle_roll
    sta rotation_mode
    sta paused
    sta frame_counter
    sta frame_counter+1
    sta f1_held
    sta f3_held
    sta space_held
    lda #24
    sta angle_pitch
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
    .for(var page=0;page<4;page++) {
        sta $0400+page*$100,x
        sta $0c00+page*$100,x
    }
    lda #1
    .for(var page=0;page<4;page++) {
        sta $d800+page*$100,x
    }
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

main:
    jsr read_keyboard
render_start:
    nop
geometry_start:
    lda model
    jsr select_model
    jsr prepare_matrix
    jsr project_vertices
geometry_end:
    nop
raster_start:
    jsr render_polygons
raster_end:
    nop
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
    lda paused
    bne !hold+
    ldx rotation_mode
    beq !all_axes+
    cpx #1
    beq !yaw_only+
    cpx #2
    beq !pitch_only+
    inc angle_roll
    jmp !hold+
!all_axes:
    inc angle_yaw
    inc angle_yaw
    inc angle_pitch
    inc angle_roll
    jmp !hold+
!yaw_only:
    inc angle_yaw
    inc angle_yaw
    jmp !hold+
!pitch_only:
    inc angle_pitch
!hold:
    jmp main

read_keyboard:
    lda #$fe
    sta $dc00
    lda $dc01
    and #$10
    bne !f1_up+
    lda f1_held
    bne !rotation+
    lda #1
    sta f1_held
    lda model
    eor #1
    sta model
    jmp !rotation+
!f1_up:
    lda #0
    sta f1_held
!rotation:
    lda $dc01
    and #$20
    bne !f3_up+
    lda f3_held
    bne !space+
    lda #1
    sta f3_held
    lda rotation_mode
    clc
    adc #1
    and #3
    sta rotation_mode
    jmp !space+
!f3_up:
    lda #0
    sta f3_held
!space:
    lda #$7f
    sta $dc00
    lda $dc01
    and #$10
    bne !space_up+
    lda space_held
    bne !done+
    lda #1
    sta space_held
    lda paused
    eor #1
    sta paused
    jmp !done+
!space_up:
    lda #0
    sta space_held
!done:
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

model: .byte 0
angle_yaw: .byte 0
angle_pitch: .byte 24
angle_roll: .byte 0
rotation_mode: .byte 0
paused: .byte 0
frame_counter: .word 0
front_screen_hi: .byte 4
back_screen_hi: .byte 12
f1_held: .byte 0
f3_held: .byte 0
space_held: .byte 0

#import "build/geometry.asm"
#import "render.asm"
#import "resolve.asm"
player_code_end:
.assert "Code below static data", * <= $4000, true

* = $4000 "Geometry and character lookup data"
raster_assets_start:
#import "build/assets/data.asm"
assets_end:
.assert "Static data below I/O", assets_end <= $d000, true
