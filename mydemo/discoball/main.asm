// Independent soccer-ball patches. The hexagon build selects the eight largest
// visible hexagons from twenty; other surfaces use the bitmap. Pentagon comparison
// builds retain twelve patches. All geometry transforms run on the C64.
.import source "build/scene.asm"
.import source "build/edge-curves.asm"
.import source "build/music.asm"
.const SPRITES_A = $0c00
.const SPRITES_B = $0e00
.const SPRITES_A_FIELD_B = $7800
.const SPRITES_B_FIELD_B = $7a00
.const MARKERS = $1800
.const FRAME_TICKS = 2
#if HEXAGON
.const SCENE_FADE_IN = 0
.const SCENE_ZOOM_IN = 1
.const SCENE_RUN = 2
.const SCENE_EXPLODE = 3
.const SCENE_FADE_OUT = 4
.const SCENE_DONE = 5
.const FACE_COUNT = 20
.const ACTIVE_SPRITES = 8
.const VERTICES_PER_FACE = 6
.const MODEL_POINTS_PER_FACE = 6
.const SPRITE_FILL_ROWS = 19
.const MARKER_CLEAR_ROWS = 20
#else
.const FACE_COUNT = 12
.const ACTIVE_SPRITES = 6
.const VERTICES_PER_FACE = 5
.const MODEL_POINTS_PER_FACE = 5
.const SPRITE_FILL_ROWS = 21
.const MARKER_CLEAR_ROWS = 21
#endif
// Front/back metadata and small vertex arrays also fit in owned zero page.
.label slotX = $02
.label slotY = $12
.label slotColor = $22
.label slotFace = $32
.label localX = $42
.label localY = $48
.label sharedX = $4e
.label sharedY = $8a
.label axisXX = $c6
.label axisXZ = $c7
.label axisYX = $c8
.label axisYY = $c9
.label axisYZ = $ca
.label axisZX = $cb
.label axisZY = $cc
.label axisZZ = $cd
.label visibleFaces = $ce
.label weakestDepth = $cf
.label secondWeakestDepth = $d0
.label weakestFace = $d1
.label secondWeakestFace = $d2
.label metadataBase = $d3
.label shownMetadataBase = $d4
.label drawBank = $d5
.label ready = $d6
.label rasterTick = $d7
.label presentationCountdown = $d8
.label normalDepth = $d9
.label presentPointer = $da
.label overflowCount = $db
.label missedDeadlines = $dc
// The relocated music player owns $de..$df; renderer temporaries start at $e0.
// Hot render temporaries; the demo owns zero page while ROM IRQs are disabled.
.label x0 = $e0
.label y0 = $e1
.label x1 = $e2
.label y1 = $e3
.label minX = $e4
.label maxX = $e5
.label minY = $e6
.label maxY = $e7
.label facePointerLow = $e8
.label facePointerHigh = $e9
.label faceIndex = $ea
.label usedSprites = $eb
.label pointTerm = $ec
.label pointIndex = $ed
.label faceVertexStart = $ee
.label polygonEdge = $ef
.label spritePointer = $f0
.label divisionPointer = $f2
.label factor = $f4
.label multiplicand = $f5
.label squareSum = $f6
.label edgeX = $f7
.label edgeEndX = $f8
.label edgeY = $f9
.label edgeDX = $fa
.label edgeError = $fb
.label edgeStep = $fc
.label edgeRemainder = $fd

BasicUpstart2(bootstrap)

// Enter RAM beneath the KERNAL only after disabling ROM reads. Keep the VIC's
// $1000..$1fff character-ROM window free of displayed sprite definitions.
bootstrap:
    sei
    lda #$35
    sta $01
    jmp start

* = $e000 "Runtime in RAM beneath KERNAL ROM"

start:
    sei
    cld
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #$35
    sta $01
    lda #<rasterIRQ
    sta $fffe
    lda #>rasterIRQ
    sta $ffff
    lda #<nmiReturn
    sta $fffa
    lda #>nmiReturn
    sta $fffb
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    // Begin on field B; the first raster IRQ switches to field A.
#if HEXAGON
    lda #$2b
#else
    lda #$3b
#endif
    sta $d011
    lda #$18+SCENE_SCROLL_XOR
    sta $d016
    lda #$f0
    sta $d018
    lda #$ff
    sta $d017
    sta $d01d
    lda #0
    sta $d01b
    sta $d020
    lda #SCENE_BACKGROUND
    sta $d021
    lda #0
    sta $d015
    sta $d01c
    sta $d010
    sta angleYaw
    sta anglePitch
    sta rasterTick
    sta ready
    sta drawBank
    sta shownMetadataBase
    sta frameNumber
    sta frameNumber+1
    sta overflowCount
    sta missedDeadlines
#if HEXAGON
    sta zoomPhase
    sta shapeMode
    sta shapePose
    sta shownShapeMode
    sta motionPhase
    sta yawFraction
    sta pitchFraction
#endif
    ldx #0
!blackScreen:
    lda backgroundColors,x
    sta $d800,x
    lda backgroundColors+$100,x
    sta $d900,x
    lda backgroundColors+$200,x
    sta $da00,x
    lda backgroundColors+$300,x
    sta $db00,x
    inx
    bne !blackScreen-
    // Copy 1000 bitmap color cells. The padded tail also initializes sprite
    // pointers; each presentation replaces the eight pointers before enabling.
    .for (var page=0; page<4; page++) {
        ldx #0
!attributes:
        lda backgroundScreen+page*$100,x
        sta $0400+page*$100,x
        inx
        bne !attributes-
    }
    // Startup can begin anywhere in the raster. Allow a complete first render
    // even if the first IRQ arrives immediately; later updates use two frames.
    lda #FRAME_TICKS+1
    sta presentationCountdown
    lda #$ff
    sta $dc04
    sta $dc05
    lda #$11
    sta $dc0e
#if HEXAGON
    jsr scenePatchMusic
    lda #MUSIC_START_SONG
    ldx #0
    ldy #0
    jsr MUSIC_INIT
    lda #8
    sta yawSpeed
    lda #4
    sta pitchSpeed
    lda #15
    sta discoPhase
    jsr sceneInit
#endif
    jsr clearMarkers
#if HEXAGON
    lda #$3b
    sta $d011
#endif
    lda #0
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    cli

nextFrame:
#if HEXAGON
    jsr sceneService
    lda sceneBallActive
    bne !render+
    jsr fadeService
    jmp nextFrame
!render:
#endif
    lda $dc04
    sta timerStart
    lda $dc05
    sta timerStart+1
    jsr prepareMatrix
#if HEXAGON
    jsr applyZoom
#endif
    jsr clearMarkers
    lda #0
    sta usedSprites
    sta faceIndex
    lda drawBank
    asl
    asl
    asl
    sta metadataBase
    tax
    lda #$ff
    .for (var slot=0; slot<8; slot++) { sta slotFace+slot,x }

#if HEXAGON
    lda sceneState
    cmp #SCENE_EXPLODE
    beq !explosion+
    lda shapeMode
    bne !pentagons+
    jsr renderHexagons
    jmp !shapeRendered+
!pentagons:
    jsr renderPentagons
    jmp !shapeRendered+
!explosion:
    jsr renderExplosion
!shapeRendered:
#else
!face:
    jsr faceDepth
    bpl !hidden+
    sta normalDepth
    jsr projectFace
    jsr drawFace
!hidden:
    inc faceIndex
    lda faceIndex
    cmp #FACE_COUNT
    bne !face-
#endif
    lda drawBank
    bne !fillB+
    jsr fillA
    jmp !filled+
!fillB:
    jsr fillB
!filled:
    lda $dc04
    sta timerEnd
    lda $dc05
    sta timerEnd+1
    lda timerStart
    sec
    sbc timerEnd
    sta renderCycles
    lda timerStart+1
    sbc timerEnd+1
    sta renderCycles+1
    lda #1
    sta ready
frameReady:
#if HEXAGON
    jsr fadeService
#endif
    lda ready
    bne frameReady
    lda drawBank
    eor #1
    sta drawBank
#if HEXAGON
    lda sceneState
    cmp #SCENE_EXPLODE
    beq !advanceExplosion+
    cmp #SCENE_RUN
    bne !advanced+
    jsr advanceMotion
    inc zoomPhase
    jsr advanceShape
    jmp !advanced+
!advanceExplosion:
    jsr advanceExplosion
!advanced:
#else
    lda angleYaw
    clc
    adc #6
    sta angleYaw
    inc anglePitch
    inc anglePitch
    inc anglePitch
#endif
    jmp nextFrame

rasterIRQ:
    pha
    txa
    pha
    tya
    pha
#if HEXAGON
    lda $01
    pha
    lda #$35
    sta $01
#endif
    inc rasterTick
    // Both MCI fields share Color RAM. Swap only the VIC bank, screen and X phase.
    lda $dd00
    eor #1
    sta $dd00
    lda $d018
    eor #$e8
    sta $d018
    lda $d016
    eor #SCENE_SCROLL_XOR
    sta $d016
#if HEXAGON
    jsr scenePalTick
    lda sceneState
    cmp #SCENE_RUN
    bne !noDisco+
    jsr updateDiscoColors
!noDisco:
    lda sceneBallActive
    beq !music+
#endif
    dec presentationCountdown
    bne !colorsOnly+
    lda #FRAME_TICKS
    sta presentationCountdown
    lda ready
    beq !missed+
    jsr presentSprites
    lda #0
    sta ready
    inc frameNumber
    bne !presented+
    inc frameNumber+1
!presented:
    jsr updateSpriteColors
framePresented:
    jmp !return+
!missed:
    inc missedDeadlines
!colorsOnly:
    jsr updateSpriteColors
!return:
#if HEXAGON
!music:
    lda sceneState
    cmp #SCENE_DONE
    beq !silent+
musicTick:
    jsr MUSIC_PLAY
musicTickEnd:
    lda sceneState
    cmp #SCENE_EXPLODE
    bcc !silent+
    ldx fadeLevel
    lda sceneSidShadow
    and #$f0
    ora sceneSidVolumes,x
    sta $d418
!silent:
#endif
    lda #1
    sta $d019
#if HEXAGON
    pla
    sta $01
#endif
    pla
    tay
    pla
    tax
    pla
nmiReturn:
    rti

presentSprites:
#if HEXAGON
    lda shapeMode
    sta shownShapeMode
#endif
    lda drawBank
    asl
    asl
    asl
    sta shownMetadataBase
    tax
    lda drawBank
    asl
    asl
    asl
    clc
    adc #SPRITES_A/64
    sta presentPointer
    .for (var slot=0; slot<8; slot++) {
        lda slotX+slot,x
        sta $d000+slot*2
        lda slotY+slot,x
        sta $d001+slot*2
        lda presentPointer
        clc
        adc #slot
        sta $07f8+slot
        clc
        adc #(SPRITES_A_FIELD_B-$4000-SPRITES_A)/64
        sta $7ff8+slot
    }
    ldx usedSprites
    lda enableMasks,x
    sta $d015
#if HEXAGON
    lda explosionXHigh
    sta $d010
#endif
    rts

// Alternate the displayed buffer's original shades on successive PAL frames.
updateSpriteColors:
#if HEXAGON
    lda sceneState
    cmp #SCENE_EXPLODE
    bne !normal+
    jmp sceneFadeSpriteColors
!normal:
#endif
    ldx shownMetadataBase
    lda rasterTick
    and #1
    beq !darker+
    .for (var slot=0; slot<8; slot++) {
        lda slotColor+slot,x
        sta $d027+slot
    }
    rts
!darker:
    .for (var slot=0; slot<8; slot++) {
        ldy slotColor+slot,x
        lda spriteDarkerColors,y
        sta $d027+slot
    }
frameColorsUpdated:
    rts

// Q6 rotation matrix: Ry(yaw), then Rx(pitch). Normals use Z for culling.
prepareMatrix:
    ldx angleYaw
    lda sine,x
    sta axisXZ
    lda cosine,x
    sta axisXX
    ldx anglePitch
    lda sine,x
    sta axisZY
    sta factor
    lda cosine,x
    sta axisYY
    lda axisXZ
    Multiply()
    sta axisYX
    lda axisXX
    Multiply()
    eor #$ff
    clc
    adc #1
    sta axisYZ
    lda axisYY
    sta factor
    lda axisXZ
    Multiply()
    eor #$ff
    clc
    adc #1
    sta axisZX
    lda axisXX
    Multiply()
    sta axisZZ
    rts

#if HEXAGON
// Scale the five X/Y projection coefficients. The normal's Z row retains its
// original rotation for face selection and lighting throughout the zoom.
applyZoom:
    lda sceneState
    cmp #SCENE_ZOOM_IN
    bne !normalZoom+
    lda sceneZoomScale
    jmp !scaleReady+
!normalZoom:
    ldx zoomPhase
    lda zoomScaleTable,x
!scaleReady:
    sta zoomScale
    cmp #64
    bne !scale+
    rts
!scale:
    sta factor
    .for (var axis=axisXX; axis<=axisYZ; axis++) {
        lda axis
        Multiply()
        sta axis
    }
    rts

// Count completed poses so the two surface sets share one continuous rotation.
// At 25.06 presentations per second, 150 hexagon poses take about six seconds
// and 50 pentagon poses take about two seconds.
advanceShape:
    inc shapePose
    lda shapeMode
    bne !pentagons+
    lda shapePose
    cmp #150
    bne !done+
    lda #1
    sta shapeMode
    lda #0
    sta shapePose
    rts
!pentagons:
    lda shapePose
    cmp #50
    bne !done+
    lda #0
    sta shapeMode
    sta shapePose
!done:
    rts

// Speeds use Q4 angle units. Preserve fractional remainders so the slow periods
// advance smoothly without rounding each quarter- or half-unit step to zero.
// The next pose advances with the old phase; speed bytes record that step.
advanceMotion:
    ldx motionPhase
    lda yawSpeedTable,x
    sta yawSpeed
    clc
    adc yawFraction
    tay
    and #15
    sta yawFraction
    tya
    lsr
    lsr
    lsr
    lsr
    clc
    adc angleYaw
    sta angleYaw
    lda pitchSpeedTable,x
    sta pitchSpeed
    clc
    adc pitchFraction
    tay
    and #15
    sta pitchFraction
    tya
    lsr
    lsr
    lsr
    lsr
    clc
    adc anglePitch
    sta anglePitch
    inc motionPhase
    rts
#endif

#if !HEXAGON
faceDepth:
    ldy faceIndex
    lda axisZX
    sta factor
    lda normalX,y
    Multiply()
    sta pointTerm
    lda axisZY
    sta factor
    lda normalY,y
    Multiply()
    clc
    adc pointTerm
    sta pointTerm
    lda axisZZ
    sta factor
    lda normalZ,y
    Multiply()
    clc
    adc pointTerm
    rts
#endif

#if HEXAGON
// Equal-size faces under orthographic projection have area proportional to
// facing depth. Hide only the weakest one or two when more than eight face us.
selectLargestHexagons:
    lda #0
    sta visibleFaces
    sta weakestDepth
    sta secondWeakestDepth
    .for (var face=0; face<FACE_COUNT; face++) {
        lda faceDepths+face
        bpl !hidden+
        inc visibleFaces
        cmp weakestDepth
        bcc !second+
        ldx weakestDepth
        stx secondWeakestDepth
        ldx weakestFace
        stx secondWeakestFace
        sta weakestDepth
        lda #face
        sta weakestFace
        jmp !hidden+
!second:
        cmp secondWeakestDepth
        bcc !hidden+
        sta secondWeakestDepth
        lda #face
        sta secondWeakestFace
!hidden:
    }
    lda visibleFaces
    cmp #9
    bcc !done+
    ldx weakestFace
    lda #0
    sta faceDepths,x
    lda visibleFaces
    cmp #10
    bcc !done+
    ldx secondWeakestFace
    lda #0
    sta faceDepths,x
!done:
    rts
#endif

projectFace:
#if HEXAGON
    // All adjoining faces fetch the same projected vertices. Derive each
    // sprite's bounds before translating those global coordinates to local.
    ldx faceIndex
    lda faceOffsets,x
    sta faceVertexStart
    tay
    lda hexFaceVertices,y
    tax
    lda sharedX,x
    sta minX
    lda sharedY,x
    sta minY
    iny
    .for (var point=1; point<VERTICES_PER_FACE; point++) {
        lda hexFaceVertices,y
        tax
        lda sharedX,x
        cmp minX
        bcs !notMinX+
        sta minX
!notMinX:
        lda sharedY,x
        cmp minY
        bcs !notMinY+
        sta minY
!notMinY:
        iny
    }
    ldy faceVertexStart
    .for (var point=0; point<VERTICES_PER_FACE; point++) {
        lda hexFaceVertices,y
        tax
        lda sharedX,x
        sec
        sbc minX
        sta localX+point
        lda sharedY,x
        sec
        sbc minY
        sta localY+point
        iny
    }
    rts
#else
    ldx faceIndex
    lda faceOffsets,x
    tay
    lda #0
    sta maxX
    sta maxY
    lda #$ff
    sta minX
    sta minY
    ldx #0
!point:
    stx pointIndex
    lda axisXX
    sta factor
    lda modelX,y
    Multiply()
    sta pointTerm
    lda axisXZ
    sta factor
    lda modelZ,y
    Multiply()
    clc
    adc pointTerm
    clc
    adc #64
    ldx pointIndex
    sta localX,x
    sta projectedX,y
    cmp minX
    bcs !notMinX+
    sta minX
!notMinX:
    cmp maxX
    bcc !notMaxX+
    sta maxX
!notMaxX:
    lda axisYX
    sta factor
    lda modelX,y
    Multiply()
    sta pointTerm
    lda axisYY
    sta factor
    lda modelY,y
    Multiply()
    clc
    adc pointTerm
    sta pointTerm
    lda axisYZ
    sta factor
    lda modelZ,y
    Multiply()
    clc
    adc pointTerm
    sta pointTerm
    lda #64
    sec
    sbc pointTerm
    ldx pointIndex
    sta localY,x
    sta projectedY,y
    cmp minY
    bcs !notMinY+
    sta minY
!notMinY:
    cmp maxY
    bcc !notMaxY+
    sta maxY
!notMaxY:
    iny
    inx
#if GOLDEN_PENTAGON
    iny
    inx
    cpx #6
#else
    cpx #5
#endif
    beq !done+
    jmp !point-
!done:
#if GOLDEN_PENTAGON
    // A regular pentagon obeys P1=P0+k*(P2-P4), P3=P4+k*(P2-P0),
    // where k=1/phi. Three well-separated corners keep rounding error bounded.
    // Project only three corners. Four small constant-multiply lookups recover
    // the remaining two; pixel rounding introduces a bounded shape difference.
    ReconstructPentagon(localX, projectedX)
    ReconstructPentagon(localY, projectedY)
    .for (var point=1; point<4; point+=2) {
        lda localX+point
        cmp minX
        bcs !notMinX+
        sta minX
!notMinX:
        cmp maxX
        bcc !notMaxX+
        sta maxX
!notMaxX:
        lda localY+point
        cmp minY
        bcs !notMinY+
        sta minY
!notMinY:
        cmp maxY
        bcc !notMaxY+
        sta maxY
!notMaxY:
    }
#endif
    rts
#endif

#if GOLDEN_PENTAGON
.macro ReconstructPentagon(local, projected) {
    ldx faceIndex
    lda faceOffsets,x
    clc
    adc #1
    tay
    lda local+2
    sec
    sbc local+4
    tax
    lda goldenRatio,x
    clc
    adc local
    sta local+1
    sta projected,y
    iny
    iny
    lda local+2
    sec
    sbc local
    tax
    lda goldenRatio,x
    clc
    adc local+4
    sta local+3
    sta projected,y
}
#endif

drawFace:
    // The generator/verifier proves these bounds. Keep guards for experiments.
#if !HEXAGON
    lda maxX
    sec
    sbc minX
    cmp #24
    bcs !overflow+
    lda maxY
    sec
    sbc minY
    cmp #21
    bcs !overflow+
#endif
    lda usedSprites
    cmp #8
    bcc !fits+
!overflow:
    inc overflowCount
    rts
!fits:
    clc
    adc metadataBase
    tax
    lda faceIndex
    sta slotFace,x
facePosition:
    lda minX
    asl
    clc
    adc #SCENE_X_BIAS
    sta slotX,x
    lda minY
    asl
    clc
    adc #SCENE_Y_BIAS
    sta slotY,x
facePositionDone:
    // Fade from the silhouette toward the face looking straight at the camera.
    // Keep the original light bands; split the darkest band into blue and purple.
    lda normalDepth
    eor #$ff
    tay
    lda spriteFadeColors,y
    sta slotColor,x
    ldx usedSprites
    lda spriteLow,x
    sta facePointerLow
    txa
    lsr
    lsr
    clc
    adc #>MARKERS
    sta spritePointer+1
    sta facePointerHigh
#if !HEXAGON
    ldx #VERTICES_PER_FACE-1
!local:
    lda localX,x
    sec
    sbc minX
    sta localX,x
    lda localY,x
    sec
    sbc minY
    sta localY,x
    dex
    bpl !local-
#endif
#if HEXAGON
    jsr drawHexEdge0
    jsr drawHexEdge1
    jsr drawHexEdge2
    jsr drawHexEdge3
    lda shapeMode
    bne !pentagonEdges+
    jsr drawHexEdge4
    jsr drawHexEdge5
    jmp !edgesDone+
!pentagonEdges:
    jsr drawPentEdge4
!edgesDone:
#else
    lda #0
    sta polygonEdge
!edge:
    ldx polygonEdge
    lda localX,x
    sta x0
    lda localY,x
    sta y0
    inx
    cpx #VERTICES_PER_FACE
    bne !next+
    ldx #0
!next:
    lda localX,x
    sta x1
    lda localY,x
    sta y1
    jsr drawBoundary
    inc polygonEdge
    lda polygonEdge
    cmp #VERTICES_PER_FACE
    bne !edge-
#endif
    inc usedSprites
    rts

// For every integer X in [left,right), toggle exactly one crossing at ceil(Y).
// Vertical edges are ignored. This endpoint rule prevents corner parity leaks.
drawBoundary:
    lda x0
    cmp x1
    bcc !ordered+
    bne !swap+
    rts
!swap:
    ldx x1
    sta x1
    stx x0
    lda y0
    ldx y1
    sta y1
    stx y0
!ordered:
    // Short-edge crossing curves replace the fractional step in the hot loop.
    // The +20 sample bias permits unsigned Y indexing for either slope sign.
    lda x0
    sta edgeX
    tax
    lda facePointerHigh
    sta spritePointer+1
    lda byteColumns,x
    clc
    adc facePointerLow
    clc
    adc y0
    sec
    sbc #20
    sta spritePointer
    bcs !pointerReady+
    dec spritePointer+1
!pointerReady:
    lda x1
    sta edgeEndX
    sec
    sbc x0
    sta edgeDX
    lda y1
    sec
    sbc y0
    clc
    adc #20
    tax
    lda curveRowsLow,x
    sta divisionPointer
    lda curveRowsHigh,x
    sta divisionPointer+1
    ldy edgeDX
    lda (divisionPointer),y
    sta curveRead+1
    lda divisionPointer+1
    clc
    adc #4
    sta divisionPointer+1
    lda (divisionPointer),y
    sta curveRead+2
    lda curveRead+1
    sec
    sbc x0
    sta curveRead+1
    bcs !curveReady+
    dec curveRead+2
!curveReady:
    ldx edgeX
!pixel:
curveRead:
    ldy $ffff,x
    lda bitMasks,x
    eor (spritePointer),y
    sta (spritePointer),y
    inx
    cpx edgeEndX
    beq !done+
    txa
    and #7
    bne !sameByte+
    lda spritePointer
    clc
    adc #21
    sta spritePointer
    bcc !sameByte+
    inc spritePointer+1
!sameByte:
    jmp !pixel-
!done:
    rts

// A*factor/64 through quarter squares. Signed inputs and Y survive the lookup.
.macro Multiply() {
    sta multiplicand
    clc
    adc factor
    tax
    lda quarterSquares,x
    sta squareSum
    lda multiplicand
    sec
    sbc factor
    tax
    lda squareSum
    sec
    sbc quarterSquares,x
}

angleYaw: .byte 0
anglePitch: .byte 0
#if HEXAGON
zoomPhase: .byte 0
zoomScale: .byte 64
shapeMode: .byte 0
shapePose: .byte 0
shownShapeMode: .byte 0
motionPhase: .byte 0
yawFraction: .byte 0
pitchFraction: .byte 0
yawSpeed: .byte 8
pitchSpeed: .byte 4
#endif
frameNumber: .word 0
timerStart: .word 0
timerEnd: .word 0
renderCycles: .word 0
#if HEXAGON
faceDepths: .fill FACE_COUNT, 0
#else
projectedX: .fill FACE_COUNT*VERTICES_PER_FACE, 0
projectedY: .fill FACE_COUNT*VERTICES_PER_FACE, 0
#endif
enableMasks: .byte 0,1,3,7,15,31,63,127,255
spriteLow: .byte 0,64,128,192,0,64,128,192
faceOffsets: .fill FACE_COUNT, i*MODEL_POINTS_PER_FACE
projectedOffsets: .fill FACE_COUNT, i*VERTICES_PER_FACE
bitMasks: .fill 24, $80 >> (i&7)
byteColumns: .fill 24, floor(i/8)*21
#if !HEXAGON
.import source "build/model.asm"
#endif

.align $100
sine: .fill 256, round(64*sin(toRadians(i*360/256))) & $ff
cosine: .fill 256, round(64*cos(toRadians(i*360/256))) & $ff
quarterSquares: .fill 256, floor(pow(i<128 ? i : i-256,2)/256)
#if HEXAGON
// Hold full size, ease to 52/64 and back over half a 256-pose cycle, then hold.
zoomScaleTable: .fill 256, (i<64 || i>=192) ? 64 : round(58+6*cos(toRadians((i-64)*360/128)))
#endif
#if GOLDEN_PENTAGON
goldenRatio: .fill 256, round((i<128 ? i : i-256)*(sqrt(5)-1)/2) & $ff
#endif
.errorif * > $f000, "Runtime overlaps fill A"

// Matching sprite buffers in both VIC banks keep the pose stable across fields.
* = SPRITES_A "Bank zero sprite sets"
.fill 1024, 0
* = SPRITES_A_FIELD_B "Bank one sprite sets"
.fill 1024, 0
* = $7c00 "MCI field B screen colors"
.import binary "build/ball-screen-b.bin"
.fill 24, 0
* = MARKERS "Column-major CPU crossing buffers"
.fill ACTIVE_SPRITES*64, 0

* = $2000 "MCI field A bitmap"
.import binary "build/ball-bitmap.bin"
* = $4000 "MCI field B bitmap"
.import binary "build/ball-bitmap-b.bin"
#if HEXAGON
* = $5f40 "Entry zoom from zero to full size"
sceneZoomTable: .fill 101, round(i*64/100)
.errorif * > $6000, "Entry zoom table overlaps projection"
#endif

.macro ClearSprites(base) {
    lda #0
    .for (var sprite=0; sprite<ACTIVE_SPRITES; sprite++) {
        .for (var column=0; column<3; column++) {
            .for (var row=0; row<MARKER_CLEAR_ROWS; row++) { sta base+sprite*64+column*21+row }
        }
    }
    rts
}
.macro FillRange(base, mirror, first, last) {
    .for (var sprite=first; sprite<last; sprite++) {
        .for (var column=0; column<3; column++) {
            lda #0
            // Hexagon spans never exceed 19; the two bottom output rows stay zero.
            .for (var row=0; row<SPRITE_FILL_ROWS; row++) {
                eor MARKERS+sprite*64+column*21+row
                sta base+sprite*64+row*3+column
                sta mirror+sprite*64+row*3+column
            }
        }
    }
}
* = $1a00 "Unrolled marker clearing"
clearMarkers: ClearSprites(MARKERS)
.errorif * > $2000, "Marker clearing overlaps bitmap A"
* = $f000 "Fill bank A, sprites zero through six"
fillA:
    FillRange(SPRITES_A, SPRITES_A_FIELD_B, 0, 7)
    jsr fillALast
    rts
.errorif * > $fffa, "Fill A overlaps hardware vectors"
* = $1490 "Fill bank A final sprite"
fillALast:
    FillRange(SPRITES_A, SPRITES_A_FIELD_B, 7, 8)
    rts
.errorif * > $16d0, "Fill A tail overlaps row tables"
* = $16d0 "Edge row pointer tables"
curveRowsLow: .fill 41, <($9800+i*24)
curveRowsHigh: .fill 41, >($9800+i*24)
.errorif * > MARKERS, "Row pointers overlap markers"
* = $6a00 "Fill bank B, sprites zero through five"
fillB:
    FillRange(SPRITES_B, SPRITES_B_FIELD_B, 0, 6)
    jsr fillBLast0
    jsr fillBLast1
    rts
.errorif * > SPRITES_A_FIELD_B, "Fill B overlaps field B sprites"
* = $0816 "Fill bank B seventh sprite"
fillBLast0:
    FillRange(SPRITES_B, SPRITES_B_FIELD_B, 6, 7)
    rts
.errorif * > SPRITES_A, "Fill B tail overlaps field A sprites"
#if HEXAGON
.errorif * > $0a20, "Fill B tail overlaps background fader"
* = $0a20 "Incremental background fader"
.import source "fade.asm"
.errorif * > SPRITES_A, "Background fader overlaps field A sprites"
* = $6000 "Shared-vertex projection specialized for constant coordinates"
.import source "build/hex-projection.asm"
.errorif * > $6a00, "Projection overlaps fill B"
* = $8000 "Coordinate products for all rotation coefficients"
.import binary "build/hex-products.bin"
.errorif * > $9400, "Hexagon tables overlap background attributes"
#endif
* = $1000 "Initial shared multicolor color RAM"
backgroundColors: .import binary "build/ball-colors.bin"
.fill 24, 0
* = $1400 "Front-facing five-color shading for sprite faces"
// Blue, purple, pink, light gray, white; saturate stronger normals.
spriteFadeColors: .fill 128, i<6 ? 6 : (i<12 ? 4 : (i<18 ? 10 : (i<24 ? 15 : 1)))
// White -> light gray -> pink -> purple -> blue; blue stays blue.
spriteDarkerColors: .byte 0,15,2,3,6,5,6,7,8,9,4,11,12,13,14,10
.errorif * > $1490, "Shade tables overlap fill A tail"
* = $9400 "Initial field A screen colors"
backgroundScreen: .import binary "build/ball-screen.bin"
.fill 24, 0
* = $9800 "Edge crossing curve pointers"
hexEdgeLow: .import binary "build/hex-edge-low.bin"
* = $9c00
hexEdgeHigh: .import binary "build/hex-edge-high.bin"
* = $a000 "Exact bounded edge crossings"
hexEdgeSamples: .import binary "build/hex-edge-samples.bin"
#if HEXAGON
.errorif * > $a800, "Edge samples overlap compact pointers"
* = $a800 "Compact edge pointer low bytes"
hexEdgeCompactLow: .import binary "build/hex-edge-compact-low.bin"
.errorif * > $a900, "Compact low pointers cross a page"
* = $a900 "Compact edge pointer high bytes"
hexEdgeCompactHigh: .import binary "build/hex-edge-compact-high.bin"
.errorif * > $aa00, "Compact high pointers cross a page"
* = $aa00 "Compact edge index bases"
hexEdgeIndexBase: .byte 10
.fill 9, 10+i*21
.errorif * > MUSIC_LOAD, "Edge pointers overlap music"
.errorif * > $ab00, "Edge pointers overlap pentagon products"
* = $ab00 "Pentagon normal coordinate products"
pentProductP24: .import binary "build/pent-products.bin"
.errorif * > $ac00, "Pentagon products overlap projection helpers"
* = $ac00 "Pentagon culling and shared-vertex gathering"
.import source "build/pent-projection.asm"
.errorif * > MUSIC_LOAD, "Pentagon helpers overlap music"
* = MUSIC_LOAD "Dance Nation by Richard Bayliss"
.import binary "build/music.bin"
.errorif * > $bc00, "Music overlaps fixed hexagon edges"
* = $bc00 "Fixed-endpoint hexagon edges"
.import source "hex-edges.asm"
.errorif * > $c200, "Fixed hexagon edges overlap disco colors"
* = $c200 "Shared Color RAM disco lights"
.import source "build/disco.asm"
.errorif * > $c410, "Disco colors overlap sprite fade lookup"
* = $c410 "Sprite colors for the eight fade levels"
fadeSpriteColors: .import binary "build/scene-fade-sprites.bin"
* = $c490 "Outro sprite-color and SID fade helpers"
sceneFadeSpriteColors: SceneFadeSpriteColors()
sceneSidVolumes: .byte 0,2,4,6,8,10,12,15
// The SID volume/filter register is write-only. Preserve the player's value in
// RAM before applying the outro volume, without reading the SID bus latch.
sceneSidWrite:
    sta $d418
    sta sceneSidShadow
    rts
sceneSidShadow: .byte 0
.errorif * > $c500, "Disco colors overlap yaw speed profile"
* = $c500 "Periodic yaw speed in Q4 angle units"
// 64 slow poses, 32 easing up, 64 fast, 32 easing down, then 64 slow.
yawSpeedTable: .fill 256, (i<64 || i>=192) ? 8 : (i<96 ? round(52-44*cos(toRadians((i-64)*180/31))) : (i<160 ? 96 : round(52+44*cos(toRadians((i-160)*180/31)))))
.errorif * > $c600, "Yaw speed profile overlaps pitch profile"
* = $c600 "Periodic pitch speed, delayed by 64 poses"
pitchSpeedTable:
.for (var phase=0; phase<256; phase++) {
    .var delayed = (phase-64) & 255
    .byte (delayed<64 || delayed>=192) ? 4 : (delayed<96 ? round(34-30*cos(toRadians((delayed-64)*180/31))) : (delayed<160 ? 64 : round(34+30*cos(toRadians((delayed-160)*180/31)))))
}
.errorif * > $c700, "Motion profiles overlap scene controller"
* = $c700 "Scene lifecycle"
.import source "scene.asm"
.errorif * > $c900, "Scene lifecycle overlaps explosion"
.import source "explosion.asm"
#endif
.errorif * > $cc34, "Scene code overlaps fill B tail"
.errorif * > $cc34, "Edge samples overlap fill B tail"
* = $cc34 "Fill bank B final sprite"
fillBLast1:
    FillRange(SPRITES_B, SPRITES_B_FIELD_B, 7, 8)
    rts
.errorif * > $d000, "Fill B tail reaches I/O"
programEnd:
#if HEXAGON
* = $d000 "Original field B attributes beneath I/O"
.import binary "build/ball-screen-b.bin"
.errorif * > $d400, "Original attributes overlap packed fade lookup"
* = $d400 "Packed attribute and Color RAM fade lookup"
.import binary "build/scene-fade.bin"
.errorif * > $dc00, "Packed fade lookup overlaps CIA RAM"
#endif
