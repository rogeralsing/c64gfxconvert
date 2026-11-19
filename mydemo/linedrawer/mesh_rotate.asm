// Rotate the object-space mesh into 8.8 camera-space coordinates. The
// second half of the vertex list is antipodal to the first.
.const meshRotated = $b000
.label meshFactor = m_a
.label meshOther = m_a+1
.label meshMulLo = prod
.label meshTerm = prod+1
.label meshTermRight = prod+2
.label meshDotLo = sm
.label meshDotHi = sm+1
.var meshProductSites = List()

.macro MeshSinCos(phase, sine, cosine) {
    lda phase
    jsr meshLoadSine
    sta sine
    lda phase
    clc
    adc #64
    jsr meshLoadSine
    sta cosine
}

.macro MeshQ6Product(left, right) {
    lda left
    ldx right
    jsr meshMulQ6
}

.macro MeshRollColumn(x, y, outX, outY) {
    MeshQ6Product(meshCR, x)
    sta meshTerm
    MeshQ6Product(meshSR, y)
    sta meshTermRight
    lda meshTerm
    sec
    sbc meshTermRight
    jsr meshClampQ6
    sta outX

    MeshQ6Product(meshSR, x)
    sta meshTerm
    MeshQ6Product(meshCR, y)
    clc
    adc meshTerm
    jsr meshClampQ6
    sta outY
}

// Y indexes coordinate + 64. The two offsets set once per frame are
// 64 + coefficient and 64 - coefficient, so the square-table indices
// are centered at 128 and can reach 256 at either axis extremum.
.macro MeshShiftProduct(coordinate) {
    ldy coordinate
    sec
    .eval meshProductSites.add(* + 1)
    lda meshQuarterLo,y
    sbc meshQuarterLo,y
    sta meshMulLo
    lda meshQuarterHi,y
    sbc meshQuarterHi,y
}

.macro MeshBiasCoordinate(source, target) {
    lda source,x
    clc
    adc #64
    sta target
}

.macro MeshAddProduct(coordinate) {
    MeshShiftProduct(coordinate)
    tay
    clc
    lda meshDotLo
    adc meshMulLo
    sta meshDotLo
    tya
    adc meshDotHi
    sta meshDotHi
}

.macro MeshRotateAxis(offset) {
    MeshShiftProduct(rx1)
    sta meshDotHi
    lda meshMulLo
    sta meshDotLo
    MeshAddProduct(ry1)
    MeshAddProduct(rz1)

    // The sum has 12 fractional bits. Convert it to 8.8 and write the
    // opposite vertex with the two-byte negation of the rounded value.
    ldx meshDotHi
    lda meshDotLo
    lsr
    lsr
    lsr
    lsr
    ora meshQ8LowBits,x
    ldy #offset
    sta (vPtr),y
    eor #$ff
    clc
    adc #1
    sta (pPtr),y
    iny
    lda meshQ8HighByte,x
    sta (vPtr),y
    eor #$ff
    adc #0
    sta (pPtr),y
}

*=$ba00 "Realtime mesh rotation"
meshRotate:
    MeshSinCos(phYaw, meshSY, meshCY)
    MeshSinCos(phPit, meshSP, meshCP)
    MeshSinCos(phRol, meshSR, meshCR)

    // Compose roll · pitch · yaw once, then apply the three matrix rows.
    MeshQ6Product(meshSP, meshSY)
    sta meshPitchFromX
    MeshQ6Product(meshSP, meshCY)
    eor #$ff
    clc
    adc #1
    sta meshPitchFromZ

    MeshRollColumn(meshCY, meshPitchFromX, meshXX, meshYX)
    MeshRollColumn(meshSY, meshPitchFromZ, meshXZ, meshYZ)

    MeshQ6Product(meshSR, meshCP)
    eor #$ff
    clc
    adc #1
    sta meshXY
    MeshQ6Product(meshCR, meshCP)
    sta meshYY

    MeshQ6Product(meshCP, meshSY)
    eor #$ff
    clc
    adc #1
    sta meshZX
    lda meshSP
    sta meshZY
    MeshQ6Product(meshCP, meshCY)
    sta meshZZ
    jsr meshPatchProducts

    lda #<meshRotated
    sta vPtr
    lda #>meshRotated
    sta vPtr+1
    lda #<(meshRotated + 3 * MESH_VERTEX_COUNT)
    sta pPtr
    lda #>(meshRotated + 3 * MESH_VERTEX_COUNT)
    sta pPtr+1
    lda #0
    sta vcount

meshRotateNext:
    ldx vcount
    MeshBiasCoordinate(meshVertexX, rx1)
    MeshBiasCoordinate(meshVertexY, ry1)
    MeshBiasCoordinate(meshVertexZ, rz1)
    MeshRotateAxis(0)
    MeshRotateAxis(2)
    MeshRotateAxis(4)

    clc
    lda vPtr
    adc #6
    sta vPtr
    bcc !noCarry+
    inc vPtr+1
!noCarry:
    clc
    lda pPtr
    adc #6
    sta pPtr
    bcc !noCarry+
    inc pPtr+1
!noCarry:
    inc vcount
    lda vcount
    cmp #(MESH_VERTEX_COUNT / 2)
    beq !done+
    jmp meshRotateNext
!done:
    rts

// Patch the two offset operands of the low-byte and high-byte reads.
// MeshShiftProduct places those fields at 0, 3, 8 and 11 bytes.
meshPatchProducts:
    ldx #0
!next:
    lda meshProductSitesLo,x
    sta vPtr
    lda meshProductSitesHi,x
    sta vPtr+1
    lda meshXX,x
    clc
    adc #64
    ldy #0
    sta (vPtr),y
    ldy #8
    sta (vPtr),y
    sta meshTerm
    lda #128
    sec
    sbc meshTerm
    ldy #3
    sta (vPtr),y
    ldy #11
    sta (vPtr),y
    inx
    cpx #9
    bcc !next-
    rts

meshProductSitesLo:
.fill meshProductSites.size(), <meshProductSites.get(i)
meshProductSitesHi:
.fill meshProductSites.size(), >meshProductSites.get(i)

// Read the shared 8.8 sine table, rounded to signed Q6.
meshLoadSine:
    jsr loadSin
    lda m_b
    clc
    adc #2
    sta m_b
    lda m_b+1
    adc #0
    cmp #$80
    ror
    ror m_b
    cmp #$80
    ror
    ror m_b
    lda m_b
    rts

// Limit rounding error at the signed Q6 axis extrema before multiplying
// by a vertex coordinate. Both operands must be in -64..64.
meshClampQ6:
    bmi !negative+
    cmp #65
    bcc !inRange+
    lda #64
    rts
!negative:
    cmp #<-64
    bcs !inRange+
    lda #<-64
!inRange:
    rts

meshMulQ6:
    jsr meshMulSignedBytes
    asl meshMulLo
    rol
    asl meshMulLo
    rol
    rts

// Exact signed byte product of A and X, high byte in A and low in
// meshMulLo. The only aliased table indices are +128 and -128.
meshMulSignedBytes:
    stx meshFactor
    sta meshOther
    clc
    adc meshFactor
    eor #$80
    tax
    lda meshOther
    sec
    sbc meshFactor
    eor #$80
    tay
    lda meshQuarterLo,x
    sec
    sbc meshQuarterLo,y
    sta meshMulLo
    lda meshQuarterHi,x
    sbc meshQuarterHi,y
    rts

meshSY: .byte 0
meshCY: .byte 0
meshSP: .byte 0
meshCP: .byte 0
meshSR: .byte 0
meshCR: .byte 0
meshPitchFromX: .byte 0
meshPitchFromZ: .byte 0
meshXX: .byte 0
meshXY: .byte 0
meshXZ: .byte 0
meshYX: .byte 0
meshYY: .byte 0
meshYZ: .byte 0
meshZX: .byte 0
meshZY: .byte 0
meshZZ: .byte 0

.assert "Mesh rotation fits before its tables", * <= $c000, true
.assert "Rotated vertices fit their working buffer", meshRotated + 6 * MESH_VERTEX_COUNT <= $b200, true

*=$c000 "Mesh fixed-point tables"
meshQuarterLo:
.fill 257, <floor(pow(i-128, 2) / 4)
*=$c200 "Mesh quarter-square high bytes"
meshQuarterHi:
.fill 257, >floor(pow(i-128, 2) / 4)
*=$c400 "Mesh Q8 conversion tables"
meshQ8LowBits:
.fill 256, <(i * 16)
meshQ8HighByte:
.fill 256, <(floor(i / 16) - 16 * floor(i / 128))
