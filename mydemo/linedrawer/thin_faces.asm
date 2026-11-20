// Screen coordinates are unsigned here. Both endpoints have passed the viewport test.
thinShort:
    lda PTAB,x
    sec
    sbc PTAB,y
    clc
    adc #2
    cmp #5
    bcs !far+
    lda PTAB+1,x
    sec
    sbc PTAB+1,y
    clc
    adc #2
    cmp #5
!far:
    rts
// The geometry references below are PTAB byte offsets (x,y interleaved).
thinClearOmissions:
    lda #0
    sta thinFound
    ldx #55
!clear:
    sta thinSkip,x
    dex
    bpl !clear-
    rts
thinDiscardEdges:
    lda #0
    sta thinCount
    // Examine the two opposite edge pairs per quad. An inside edge can
    // collapse only onto the opposite silhouette within two logical pixels.
    ldx #0
!face:
    ldy thinTestFace,x
    lda meshVisibleFaces,y
    beq !next+
    ldy thinF0,x
    lda meshVisibleFaces,y
    sta thinSwap
    ldy thinF2,x
    eor meshVisibleFaces,y
    beq !next+
    stx thinIndex
    ldy thinD,x
    lda thinA,x
    tax
    jsr thinShort
    bcs !restore+
    ldx thinIndex
    ldy thinC,x
    lda thinB,x
    tax
    jsr thinShort
    bcs !restore+
    jsr thinAssign
!restore:
    ldx thinIndex
!next:
    inx
    cpx #32
    bne !face-
    ldx thinCount
    beq !done+
!apply:
    dex
    stx thinIndex
    lda thinFrom,x
    tax
    ldy thinTo,x
    lda PTAB,y
    sta PTAB,x
    lda PTAB+1,y
    sta PTAB+1,x
    lda #255
    sta thinTo,x
    ldx thinIndex
    bne !apply-
!done:
    rts

thinAssign:
    ldx thinIndex
    lda thinSwap
    bne !reverse+
    lda thinA,x
    sta thinOuterA
    lda thinB,x
    sta thinOuterB
    lda thinD,x
    sta thinInnerA
    lda thinC,x
    sta thinInnerB
    ldy thinE2,x
    jmp !test+
!reverse:
    lda thinD,x
    sta thinOuterA
    lda thinC,x
    sta thinOuterB
    lda thinA,x
    sta thinInnerA
    lda thinB,x
    sta thinInnerB
    ldy thinE0,x
!test:
    // The silhouette edge must span at least eight logical pixels.
    sty thinEdge
    ldx thinOuterA
    ldy thinOuterB
    lda PTAB,x
    sec
    sbc PTAB,y
    clc
    adc #7
    cmp #15
    bcs !long+
    lda PTAB+1,x
    sec
    sbc PTAB+1,y
    clc
    adc #7
    cmp #15
    bcc !done+
!long:
    ldy thinEdge
    lda #1
    sta thinSkip,y
    sta thinFound
    ldx thinInnerA
    ldy thinOuterA
    jsr thinRemember
    ldx thinInnerB
    ldy thinOuterB
    jmp thinRemember
!done:
    rts

// Silhouette vertices stay fixed. If multiple collapses can reach an
// interior vertex, keep the closest silhouette position.
thinRemember:
    stx thinInner
    sty thinOuter
    ldy thinIncidentStart,x
!incident:
    ldx thinIncident,y
    bmi !eligible+
    lda meshVisibleFaces,x
    beq !done+
    iny
    bne !incident-
!eligible:
    ldx thinInner
    ldy thinOuter
    // Candidate is within two pixels. The x/y maximum is its screen distance.
    lda PTAB,x
    sec
    sbc PTAB,y
    tax
    lda thinAbs,x
    sta thinDX
    ldx thinInner
    lda PTAB+1,x
    sec
    sbc PTAB+1,y
    tax
    lda thinAbs,x
    cmp thinDX
    bcs !rank+
    lda thinDX
!rank:
    ldx thinInner
    ldy thinTo,x
    bmi !new+
    cmp thinScore,x
    bcs !done+
    bcc !write+
!new:
    ldy thinCount
    pha
    txa
    sta thinFrom,y
    pla
    inc thinCount
!write:
    sta thinScore,x
    lda thinOuter
    sta thinTo,x
!done:
    rts
thinSwap: .byte 0
thinIndex: .byte 0
thinInnerA: .byte 0
thinInnerB: .byte 0
thinOuterA: .byte 0
thinOuterB: .byte 0
thinOuter: .byte 0
thinInner: .byte 0
thinDX: .byte 0
thinEdge: .byte 0
thinCount: .byte 0
thinFound: .byte 0
thinSkip: .fill 56,0
thinFrom: .fill 26,0
thinTo: .fill 52,255
thinScore: .fill 52,0
thinAbs: .fill 256, i<128 ? i : 256-i
// The generator packs nine 32-entry columns, then one offset per projected
// coordinate byte, followed by each vertex's terminated list of faces.
thinTestFace: .import binary "build/thin-topology.bin"
.label thinF0 = thinTestFace + 32
.label thinF2 = thinF0 + 32
.label thinE0 = thinF2 + 32
.label thinE2 = thinE0 + 32
.label thinA = thinE2 + 32
.label thinB = thinA + 32
.label thinC = thinB + 32
.label thinD = thinC + 32
.label thinIncidentStart = thinD + 32
.label thinIncident = thinIncidentStart + 2 * MESH_VERTEX_COUNT
.assert "Snap planner fits below charset A", * <= $2000,true

// Each quad has a preselected short-edge candidate. If none are close,
// the globe can take the unmodified in-bounds draw path.
*=$e520 "Unrolled projected-edge proximity gate"
thinGate:
.var gateEdges = LoadBinary("build/thin-gate.bin")
.assert "The globe proximity gate covers 16 opposite-edge pairs", gateEdges.getSize() == 32, true
.for (var edge = 0; edge < gateEdges.getSize(); edge += 2) {
    .var a = gateEdges.get(edge)
    .var b = gateEdges.get(edge + 1)
    .for (var axis = 0; axis < 2; axis++) {
        lda PTAB + a + axis
        sec
        sbc PTAB + b + axis
        tax
        lda thinNear,x
        beq !next+
    }
    jmp thinDiscardEdges
!next:
}
    rts
.assert "Gate ends below writable masks", * <= $e700,true
*=$cf00 "Near coordinate deltas"
thinNear: .fill 256, (i<3 || i>253) ? 1 : 0
