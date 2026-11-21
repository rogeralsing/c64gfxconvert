// Every vertex samples the same travelling sine field in screen space.
// Two offsets per axis deform the glyph while keeping joined strokes together.
.const SCROLL_START = cmdLineVars.get("scrollStart").asNumber()
.const SCROLL_LEFT = cmdLineVars.get("scrollLeft").asNumber()
.const SCROLL_SPACING = cmdLineVars.get("scrollSpacing").asNumber()
.const SCROLL_STEP = cmdLineVars.get("scrollStep").asNumber()
.const SCROLL_WAVE_CENTER = cmdLineVars.get("waveCenter").asNumber()
.const LETTER_COUNT = 27
.const LETTER_STRIDE = 16
.const SPACE_GLYPH = 26
.const POINT_COUNT = 35

.label scX0Hi = $42
.label scX1Hi = $43
.label scPhaseX1 = $44
.label scPhaseX2 = $45
.label scPhaseY1 = $46
.label scPhaseY2 = $47
.label scCoordsLo = $48
.label scCoordsHi = $49
.label scEdgesLo = $4a
.label scEdgesHi = $4b
.label scPoint = $4c
.label scFirstOffset = $4d

* = $c400 "Line scroller driver"
drawScroller:
    lda scMotionPhase
    asl
    sta scTimeTwice
    clc
    adc scMotionPhase
    sta scTimeThrice
    lda scFirstLo
    sta scCenterLo
    lda scFirstHi
    sta scCenterHi
    lda scFirstGlyph
    sta scTextIndex
!glyphLoop:
    lda scCenterHi
    bmi !visible+
    lda scCenterLo
    cmp #SCROLL_START
    bcs scAdvance
!visible:
    ldx scTextIndex
    lda scMessage,x
    cmp #$ff
    bne !glyphReady+
    ldx #0
    stx scTextIndex
    lda scMessage
!glyphReady:
    cmp #SPACE_GLYPH
    beq !move+
    tax
    jsr scDrawGlyph
!move:
    inc scTextIndex
    clc
    lda scCenterLo
    adc #SCROLL_SPACING
    sta scCenterLo
    lda scCenterHi
    adc #0
    sta scCenterHi
    jmp !glyphLoop-

scAdvance:
    // The deformation clock advances once for every two displayed positions.
    lda scHalfStep
    eor #1
    sta scHalfStep
    bne !scroll+
    inc scMotionPhase
!scroll:
    sec
    lda scFirstLo
    sbc #SCROLL_STEP
    sta scFirstLo
    lda scFirstHi
    sbc #0
    sta scFirstHi
    bpl !done+
    lda scFirstLo
    cmp #<SCROLL_LEFT
    bcs !done+
    clc
    adc #SCROLL_SPACING
    sta scFirstLo
    lda scFirstHi
    adc #0
    sta scFirstHi
    ldx scFirstGlyph
    inx
    lda scMessage,x
    cmp #$ff
    bne !keep+
    ldx #0
!keep:
    stx scFirstGlyph
!done:
    rts

scDrawGlyph:
    lda scCoordsPageLo,x
    sta scCoordsLo
    lda scCoordsPageHi,x
    sta scCoordsHi
    lda scEdgesPageLo,x
    sta scEdgesLo
    lda scEdgesPageHi,x
    sta scEdgesHi
    lda scCounts,x
    sta scNodeCount
    jsr scSetPhases

    // Transform each vertex once. Joined strokes share its screen position.
    ldx #0
!node:
    txa
    tay
    lda (scCoordsLo),y
    sta scPoint
    tay
    lda scVertexPhaseX1,y
    clc
    adc scPhaseX1
    tay
    lda scSineX1,y
    sta scFirstOffset
    ldy scPoint
    lda scVertexPhaseX2,y
    clc
    adc scPhaseX2
    tay
    lda scSineX2,y
    clc
    adc scFirstOffset
    ldy scPoint
    clc
    adc scVertexX,y
    bmi !left+
    clc
    adc scCenterLo
    sta scNodeXLo,x
    lda scCenterHi
    adc #0
    jmp !xReady+
!left:
    clc
    adc scCenterLo
    sta scNodeXLo,x
    lda scCenterHi
    adc #$ff
!xReady:
    sta scNodeXHi,x
    ldy scPoint
    lda scVertexPhaseY1,y
    clc
    adc scPhaseY1
    tay
    lda scSineY1,y
    sta scFirstOffset
    ldy scPoint
    lda scVertexPhaseY2,y
    clc
    adc scPhaseY2
    tay
    lda scSineY2,y
    clc
    adc scFirstOffset
    ldy scPoint
    clc
    adc scVertexY,y
    clc
    adc #SCROLL_WAVE_CENTER
    sta scNodeY,x
    inx
    cpx scNodeCount
    bne !node-

    lda #0
    sta scEdgeIndex
!edge:
    ldy scEdgeIndex
    lda (scEdgesLo),y
    cmp #$ff
    beq !done+
    pha
    and #$0f
    tax
    lda scNodeXLo,x
    sta lx1
    lda scNodeXHi,x
    sta scX1Hi
    lda scNodeY,x
    sta ly1
    pla
    lsr
    lsr
    lsr
    lsr
    tax
    lda scNodeXLo,x
    sta lx0
    lda scNodeXHi,x
    sta scX0Hi
    lda scNodeY,x
    sta ly0
    jsr drawScrollerLine
    inc scEdgeIndex
    jmp !edge-
!done:
    rts

scSetPhases:
    // Add the glyph origin and time once, then add local phases per vertex.
    lda scCenterLo
    asl
    sta scPhaseX1
    // The main Y wave travels right, against the leftward scroll.
    sec
    sbc scTimeThrice
    sta scPhaseY1
    lda scPhaseX1
    clc
    adc scCenterLo
    tay
    clc
    adc scTimeThrice
    sta scPhaseX2
    tya
    sec
    sbc scTimeTwice
    sta scPhaseY2
    lda scPhaseX1
    sec
    sbc scTimeTwice
    sta scPhaseX1
    rts

scFirstLo:
    .byte <SCROLL_START
scFirstHi:
    .byte >SCROLL_START
scFirstGlyph:
    .byte 0
scHalfStep:
    .byte 0
scMotionPhase:
    .byte 0
scCenterLo:
    .byte 0
scCenterHi:
    .byte 0
scTimeTwice:
    .byte 0
scTimeThrice:
    .byte 0
scTextIndex:
    .byte 0
scNodeCount:
    .byte 0
scEdgeIndex:
    .byte 0
scNodeXLo:
    .fill LETTER_STRIDE, 0
scNodeXHi:
    .fill LETTER_STRIDE, 0
scNodeY:
    .fill LETTER_STRIDE, 0
.assert "Line scroller driver fits before I/O", * <= $d000, true

* = $5000 "Line scroller sine and vertex tables"
scSineX1:
    .import binary ASSET_DIR + "/scroll-sine.bin"
.label scSineX2 = scSineX1 + $100
.label scSineY1 = scSineX1 + $200
.label scSineY2 = scSineX1 + $300
.assert "Scroller uses four complete sine pages", * == scSineX1 + $400, true
scVertexX:
    .import binary ASSET_DIR + "/scroll-vertices.bin"
.label scVertexY = scVertexX + POINT_COUNT
.label scVertexPhaseX1 = scVertexY + POINT_COUNT
.label scVertexPhaseX2 = scVertexPhaseX1 + POINT_COUNT
.label scVertexPhaseY1 = scVertexPhaseX2 + POINT_COUNT
.label scVertexPhaseY2 = scVertexPhaseY1 + POINT_COUNT
.assert "Scroller vertex table covers the point grid", * == scVertexY + 5 * POINT_COUNT, true
.assert "Sine and vertex tables fit before short-line decisions", * <= shortDecisionBits, true

* = $a400 "Line scroller stroke font"
scCoordinates:
    .import binary ASSET_DIR + "/letter-coords.bin"
scEdges:
    .import binary ASSET_DIR + "/letter-edges.bin"
scCounts:
    .import binary ASSET_DIR + "/letter-counts.bin"
scMessage:
    .import binary ASSET_DIR + "/letter-message.bin"
scCoordsPageLo:
    .fill LETTER_COUNT, <(scCoordinates + i * LETTER_STRIDE)
scCoordsPageHi:
    .fill LETTER_COUNT, >(scCoordinates + i * LETTER_STRIDE)
scEdgesPageLo:
    .fill LETTER_COUNT, <(scEdges + i * LETTER_STRIDE)
scEdgesPageHi:
    .fill LETTER_COUNT, >(scEdges + i * LETTER_STRIDE)
.assert "Stroke layout matches native point and edge tables", scEdges - scCoordinates == LETTER_COUNT * LETTER_STRIDE && scCounts - scEdges == LETTER_COUNT * LETTER_STRIDE, true
.assert "Stroke font fits before patch rows", * <= $b200, true

#import "clip_x.asm"
