// Resolve each temporary index to a prebuilt covering glyph, then update
// its screen cell once. The character bitmap stays fixed.
*=$9500 "Known glyph masks and pending joins"
.import binary "build/revlo.bin"
.import binary "build/revhi.bin"
*=$a480 "Pending screen cells"
coverScreenLo: .fill 55,0
coverScreenHi: .fill 55,0
coverOffset: .byte 0

*=$a300 "Fixed-glyph row addresses low"
coverLo: .import binary "build/cover-lo.bin"
*=$b700 "Fixed-glyph row addresses high"
coverHi: .import binary "build/cover-hi.bin"
*=$e800 "Common fixed-glyph rows"
.import binary "build/cover-direct.bin"
*=$f000 "Fixed-glyph decision lists"
.import binary "build/cover-lists.bin"
.assert "Join tables fit below interrupt vectors", * <= $fffa, true

*=$2a00 "Resolve pending screen cells using the immutable font"
flushFixedJunctions:
    ldx #201
!loop:
    cpx nextPatch
    beq !done+
    ldy exactMaskHi,x
    lda coverLo,y
    sta dstLo
    lda coverHi,y
    sta dstHi
    cmp #$f0
    bcs !list+
    ldy exactMaskLo,x
    lda (dstLo),y
    jmp !write+
!list:
    lda exactMaskLo,x
    sta patLo
    ldy #0
!candidate:
    lda (dstLo),y
    and patLo
    beq !found+
    iny
    iny
    bne !candidate-
!found:
    iny
    lda (dstLo),y
!write:
    ldy coverScreenLo-201,x
    sty jptrLo
    ldy coverScreenHi-201,x
    sty jptrHi
    ldy #0
    sta (jptrLo),y
    inx
    bne !loop-
!done:
    rts
