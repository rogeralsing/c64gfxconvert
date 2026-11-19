// Separate steady-state loop for every major/minor direction pair.
.var kernelLo = List()
.var kernelHi = List()

.macro HoleFullKernel(o) {
    .var major = ScreenMajor(o)
    .var minor = ScreenMinor(o)
    .var both = major + minor
    .var row = 64 * o
    ldy holeWindowIndex
    lda (holeTrace),y
    tay
    lda (holeShiftPtr),y
    .if (o >= 4 && minor < 0) { eor #32 }
    tax
    ldy #max(0,-minor)
    lda (scrLo),y
    beq !empty+
    cmp #HOLE_CODE
    beq !second+
    cmp holeFullFirst + row,x
    beq !second+
    lda #HOLE_CODE
    bne !write+
!empty:
    lda holeFullFirst + row,x
!write:
    sta (scrLo),y
!second:
    lda holeFullSecond + row,x
    beq !advance+
    sta jcode
    ldy #max(0,minor)
    lda (scrLo),y
    beq !empty+
    cmp #HOLE_CODE
    beq !advance+
    cmp jcode
    beq !advance+
    lda #HOLE_CODE
    bne !write+
!empty:
    lda jcode
!write:
    sta (scrLo),y
!advance:
    .if (o >= 4) {
        // Keys 32..63 cross a cell. Westward kernels inverted that flag above.
        cpx #32
        lda scrLo
        adc #<(major + min(minor,0))
        sta scrLo
        .if (major > 0) { bcc !done+ } else { bcs !done+ }
        .if (major > 0) { inc scrHi } else { dec scrHi }
    } else {
        cpx #32
        bcs !diagonal+
        lda scrLo
        adc #<major
        sta scrLo
        .if (major > 0) { bcc !done+ } else { bcs !done+ }
        .if (major > 0) { inc scrHi } else { dec scrHi }
        jmp !done+
    !diagonal:
        lda scrLo
        adc #<(both-1)
        sta scrLo
        .if (both > 0) { bcc !done+ } else { bcs !done+ }
        .if (both > 0) { inc scrHi } else { dec scrHi }
    }
!done:
    inc holeWindowIndex
}

*=$9100 "Direction-specialized group kernels"
.for (var o=0; o<8; o++) {
    // Reuse the exact-join artwork and lookup banks in the fixed-font build.
    .if (o==4) {
        .assert "First four kernels fit below the alignment decoder", * <= phase2, true
        *=$2800 "Full blocks for directions 4 and 5"
    }
    .if (o==6) {
        .assert "Directions 4 and 5 fit below screen B", * <= SCREEN_B, true
        *=$b600 "Full blocks for direction 6"
    }
    .if (o==7) {
        .assert "Direction 6 fits below the horizontal reversal table", * <= $b800, true
        *=$a200 "Full blocks for direction 7"
    }
    .var top = *
    .for (var block=0; block<HOLE_UNROLL; block++) {
        .eval kernelLo.add(<*)
        .eval kernelHi.add(>*)
        HoleFullKernel(o)
    }
    dec holeFullCount
    bmi !tail+
    jmp top
!tail:
    jmp holeDrawTail
}
.assert "Direction 7 fits below clear routines", * <= $a400, true
*=$7f00 "Full group entry points"
kernelStartLo:
.for (var block=0; block<HOLE_UNROLL; block++) {
    .for (var o=0;o<8;o++) { .byte kernelLo.get(o*HOLE_UNROLL+block) }
}
kernelStartHi:
.for (var block=0; block<HOLE_UNROLL; block++) {
    .for (var o=0;o<8;o++) { .byte kernelHi.get(o*HOLE_UNROLL+block) }
}
.assert "Direction entries fit below reciprocals", * <= $8000, true

*=$1100 "Full-group indexing helpers"
kernelLane:
    .fill 41, ((-i)&(HOLE_UNROLL-1))*8
kernelLastLoop:
    .fill 41, floor((i-1)/HOLE_UNROLL)&255
