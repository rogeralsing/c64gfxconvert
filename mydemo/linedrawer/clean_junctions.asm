// Each colliding back-buffer cell can own one of 55 temporary indices.
// Y is the stored code, X the incoming fixed stamp. Return the cell code in A.
.label exactMaskLo = FIXED_JUNCTION_FONT ? $9500 : $e700
.label exactMaskHi = exactMaskLo + $100
.label flushJunctions = FIXED_JUNCTION_FONT ? flushFixedJunctions : flushPatchedJunctions

*=$1a00 "Glyph unions and thin face classification"
mergeJunction:
    lda exactMaskLo,y
    ora exactMaskLo,x
    sta patLo
    lda exactMaskHi,y
    ora exactMaskHi,x
    .if (FIXED_JUNCTION_FONT) { sta patHi }
    cpy #201
    bcs !save+
    // A fixed glyph that already covers the union needs no scratch cell.
    .if (FIXED_JUNCTION_FONT) {
        cmp exactMaskHi,y
        bne !new+
        lda patLo
        cmp exactMaskLo,y
        bne !new+
        tya
        rts
    !new:
        lda patHi
        cmp exactMaskHi,x
        bne !alloc+
        lda patLo
        cmp exactMaskLo,x
        bne !alloc+
        txa
        rts
    !alloc:
    }
    ldx nextPatch
    beq !saturated+
    ldy nextPatch
    inc nextPatch
    .if (FIXED_JUNCTION_FONT) {
        lda scrLo
        clc
        adc coverOffset
        sta coverScreenLo-201,y
        lda scrHi
        adc #0
        sta coverScreenHi-201,y
    }
!save:
    .if (FIXED_JUNCTION_FONT) { lda patHi }
    sta exactMaskHi,y
    lda patLo
    sta exactMaskLo,y
    tya
    rts
!saturated:
    inc exactOverflow
    tya
    rts

.import source "thin_faces.asm"

.if (FIXED_JUNCTION_FONT) {
    .import source "resolve_fixed_junctions.asm"
} else {
    .import source "resolve_patched_junctions.asm"
}
