// Measure oscillator sample-and-hold transfer through voice 3's OSC3 readback.
// Each of the 256 input codes is used once. $D418 remains constant at 15.
BasicUpstart2(start)
start:
    sei
    cld
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $dc0e
    sta $dd0e
    sta $d011
    sta $d015
    lda #$35
    sta $01
    lda #0
    ldx #24
!clear:
    sta $d400,x
    dex
    bpl !clear-
    lda #$f0
    sta $d414
    lda #15
    sta $d418
    lda #1
    sta $d412
    ldy #32
!warmup:
    ldx #0
!delay:
    dex
    bne !delay-
    dey
    bne !warmup-
    ldx #0
!level:
    lda #9
    sta $d412
    txa
    sta $d40f
    lda #1
    sta $d412
    // 92 NOP cycles plus the 6-cycle enable instruction reach a known phase.
    .fill 46, $ea
    lda #$11
    sta $d412
    lda $d41b
    sta observations,x
    lda #1
    sta $d412
    inx
    bne !level-
done:
    jmp done
observations:
    .fill 256,0
program_end:
