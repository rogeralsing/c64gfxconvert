// Stock PAL C64 MCI parallax: one static sky and three independently scrolling bands.
// Each phase has two bitmap buffers below the sky. Background work prepares the next
// coarse column; screen colors and shared Color RAM commit only after phase B finishes.

.const SCREEN_A = $6000
.const SCREEN_B = $e000
.const BITMAP_A = $4000
.const BITMAP_B = $c000
.const ACTOR_A = $6400
.const ACTOR_B = $e400
.const COPY_POINTER = $fb
.const RIDER_X = 112
.const RIDER_Y = 131
.const COPY_GUARD_LINES = 20
.var BAND_FIRST_ROWS = List().add(12, 16, 20)
.var BAND_ROW_COUNTS = List().add(4, 4, 5)

BasicUpstart2(start)

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
    sta paused
    sta spaceHeld
    sta frameCounter
    sta frameCounter+1
    sta motionCounter
    sta animationFrame
    sta pairCounter
    sta scheduleIndex
    sta pendingMask
    sta copyAvailableLines
    sta $d020
    sta $d010
    sta $d017
    sta $d01b
    sta $d01d
    sta $d025
    lda #$0f
    sta $d019
    lda #$0b
    sta $d011
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda #<irq
    sta $fffe
    lda #>irq
    sta $ffff
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    sta phaseBankValues+1
    ora #2
    sta phaseBankValues
    sta $dd00

    // Phase B's bitmap crosses the CPU's I/O window. Copy it with all RAM visible.
    lda #$34
    sta $01
    ldx #0
copyPhaseBPages:
    .for (var page = 0; page < 31; page++) {
        lda stagedBitmapB + page * $100,x
        sta BITMAP_B + page * $100,x
    }
    inx
    beq phaseBPagesReady
    jmp copyPhaseBPages
phaseBPagesReady:
    ldx #0
copyPhaseBTail:
    lda stagedBitmapB+$1f00,x
    sta BITMAP_B+$1f00,x
    inx
    cpx #64
    bne copyPhaseBTail
    ldx #0
copyPhaseBScreen:
    .for (var page = 0; page < 3; page++) {
        lda stagedScreenB + page * $100,x
        sta SCREEN_B + page * $100,x
    }
    inx
    bne copyPhaseBScreen
    ldx #0
copyPhaseBScreenTail:
    lda stagedScreenB+$300,x
    sta SCREEN_B+$300,x
    inx
    cpx #232
    bne copyPhaseBScreenTail
    ldx #0
copyPhaseBActors:
    .for (var page = 0; page < 10; page++) {
        lda ACTOR_A + page * $100,x
        sta ACTOR_B + page * $100,x
    }
    inx
    bne copyPhaseBActors
    ldx #0
copyPhaseBActorTail:
    lda ACTOR_A+$a00,x
    sta ACTOR_B+$a00,x
    inx
    cpx #64
    bne copyPhaseBActorTail
    lda #$35
    sta $01
    ldx #0
copyColors:
    .for (var page = 0; page < 3; page++) {
        lda stagedColors + page * $100,x
        and #15
        sta $d800 + page * $100,x
    }
    inx
    bne copyColors
    ldx #0
copyColorTail:
    lda stagedColors+$300,x
    and #15
    sta $db00,x
    inx
    cpx #232
    bne copyColorTail

    lda #0
    ldx #2
initializeBands:
    sta fineValues,x
    sta coarseValues,x
    sta activeBuffers,x
    sta jobStates,x
    sta jobPhases,x
    sta jobColumns,x
    sta jobColumnsB,x
    sta pendingCommits,x
    sta pendingFine,x
    sta stallCounts,x
    lda #$10
    sta fineRegisterValues,x
    ora skyPhase
    sta displayRegisterValues,x
    lda #$80
    sta bitmapRegisters,x
    lda bandRoutineBase,x
    sta routineBases,x
    clc
    adc #6
    sta routineBasesB,x
    lda #0
    dex
    bpl initializeBands

    // Prepare every first back buffer before the first displayed field.
prepareInitialBuffers:
    jsr chooseCopyJob
    bcs prepareInitialBuffers
    jsr prepareCopyCall
    jsr copyChunk
    jsr advanceCopyJob
    lda jobStates
    and jobStates+1
    and jobStates+2
    beq prepareInitialBuffers

    lda backgroundColor
    sta $d021
    lda #13
    sta $d026
    lda #$7f
    sta $d01c
    sta $d015
    .for (var slot = 0; slot < 7; slot++) {
        lda mountedOffsets + slot * 2
        clc
        adc #RIDER_X
        sta $d000 + slot * 2
        lda mountedOffsets + slot * 2 + 1
        clc
        adc #RIDER_Y
        sta $d001 + slot * 2
        lda #5
        sta $d027 + slot
    }
    lda #$ff
    sta $dc02
    sta $dc00
    lda #0
    sta $dc03
    lda #$80
    sta $d018
    lda #$18
    sta $d016
    lda #$0b
    sta $d011
    NextIRQ(40, irqHeader)
    lda #1
    sta skyPhase
    sta $d01a
    cli

main:
    // Attribute commits are interruptible. Their band's phase-B image is already complete.
    lda pendingMask
    beq !copyWork+
    ldx #0
!findCommit:
    lda pendingCommits,x
    bne !commit+
    inx
    cpx #3
    bne !findCommit-
!copyWork:
    jsr chooseCopyJob
    bcs main
    jsr prepareCopyCall
    jsr copyChunk
    jsr advanceCopyJob
    jmp main
!commit:
    stx workBand
    lda commitLow,x
    sta COPY_POINTER
    lda commitHigh,x
    sta COPY_POINTER+1
    jsr runIndirect
    ldx workBand
    // Publish bitmap selection, camera and new preparation job together.
!waitPublishWindow:
    jsr copyWindowSafe
    cmp #6
    bcc !waitPublishWindow-
    php
    sei
    lda activeBuffers,x
    eor #1
    sta activeBuffers,x
    asl
    asl
    asl
    ora #$80
    sta bitmapRegisters,x
    lda activeBuffers,x
    beq !baseZero+
    lda bandRoutineBase,x
    clc
    adc #3
    bne !baseReady+
!baseZero:
    lda bandRoutineBase,x
!baseReady:
    sta routineBases,x
    clc
    adc #6
    sta routineBasesB,x
    lda pendingFine,x
    sta fineValues,x
    ora #$10
    sta fineRegisterValues,x
    ora skyPhase
    sta displayRegisterValues,x
    inc coarseValues,x
    lda coarseValues,x
    cmp #40
    bcc !cameraReady+
    lda #0
    sta coarseValues,x
!cameraReady:
    lda #0
    sta pendingCommits,x
    sta jobStates,x
    sta jobPhases,x
    sta jobColumns,x
    sta jobColumnsB,x
    lda pendingCommits
    ora pendingCommits+1
    ora pendingCommits+2
    sta pendingMask
    plp
mainComplete:
    jmp main

chooseCopyJob:
    ldy #7
!try:
    ldx scheduleIndex
    lda workSchedule,x
    sta workBand
    inc scheduleIndex
    lda scheduleIndex
    cmp #7
    bcc !indexReady+
    lda #0
    sta scheduleIndex
!indexReady:
    ldx workBand
    lda jobStates,x
    bne !skip+
    lda jobColumns,x
    cmp #40
    bcs !phaseB+
    lda #0
    sta jobPhases,x
    clc
    rts
!phaseB:
    lda jobColumnsB,x
    cmp #40
    bcs !skip+
    lda #1
    sta jobPhases,x
    clc
    rts
!skip:
    dey
    bne !try-
    sec
    rts

prepareCopyCall:
    ldx workBand
    lda #2
    sta copyColumns
    lda jobPhases,x
    beq !phaseA+
    lda jobColumnsB,x
    tay
    lda routineBasesB,x
    jmp !baseReady+
!phaseA:
    lda jobColumns,x
    tay
    lda routineBases,x
!baseReady:
    clc
    adc columnRoutineOffsets,y
    sta routineIndex
    tax
    lda copyRoutineLow,x
    sta COPY_POINTER
    lda copyRoutineHigh,x
    sta COPY_POINTER+1
    lda columnByteOffsets,y
    sta copyOffset
    sty copyColumn
    rts

copyWindowSafe:
    // Keep atomic band publication clear of the next raster IRQ. PAL has 312 lines.
    lda $d012
    sta copyRaster
    bit $d011
    bmi !highRaster+
    lda nextRaster
    sec
    sbc copyRaster
    bcs !distanceReady+
    clc
    adc #56
    jmp !distanceReady+
!highRaster:
    lda nextRaster
    clc
    adc #56
    sec
    sbc copyRaster
!distanceReady:
    cmp #COPY_GUARD_LINES
    rts

copyChunk:
    ldx workBand
    lda jobPhases,x
    beq !mapped+
    lda #$34
    sta $01
!mapped:
    lda #8
    sta copyColumns
    ldx copyOffset
    jsr runIndirect
    lda copyOffset
    clc
    adc #16
    tax
    jsr runIndirect
    lda copyOffset
    clc
    adc #32
    tax
    jsr runIndirect
    lda copyColumn
    cmp #32
    beq !wrapColumns+
    lda copyOffset
    clc
    adc #48
    tax
    jsr runIndirect
    jmp !done+
!wrapColumns:
    ldx routineIndex
    inx
    lda copyRoutineLow,x
    sta COPY_POINTER
    lda copyRoutineHigh,x
    sta COPY_POINTER+1
    ldx #0
    jsr runIndirect
!done:
    lda #$35
    sta $01
    rts

runIndirect:
    jmp (COPY_POINTER)

advanceCopyJob:
    ldx workBand
    lda jobPhases,x
    beq !phaseA+
    lda jobColumnsB,x
    clc
    adc copyColumns
    sta jobColumnsB,x
    jmp !checkReady+
!phaseA:
    lda jobColumns,x
    clc
    adc copyColumns
    sta jobColumns,x
!checkReady:
    lda jobColumns,x
    cmp #40
    bcc !done+
    lda jobColumnsB,x
    cmp #40
    bcc !done+
    lda #1
    sta jobStates,x
!done:
    rts

irq:
    pha
    lda $01
    pha
    lda #$35
    sta $01
    txa
    pha
    tya
    pha
irqDispatch:
    jmp irqHeader

irqHeader:
    lda #1
    sta $d019
    lda skyPhase
    eor #1
    sta skyPhase
    lda fineRegisterValues+1
    ora skyPhase
    sta roadDisplayFine
    lda skyPhase
    tax
    lda phaseBankValues,x
    sta $dd00
    lda #$80
    sta $d018
    lda skyScrollValues,x
    sta $d016
    lda #$3b
    sta $d011
    lda #0
    sta $d01b
    jsr readSpace
    lda paused
    bne !noMotion+
    inc motionCounter
    lda skyPhase
    beq !noMotion+
    inc pairCounter
!noMotion:
    lda motionCounter
    lsr
    and #7
    sta animationFrame
    asl
    asl
    asl
    sec
    sbc animationFrame
    tax
    .for (var slot = 0; slot < 7; slot++) {
        lda mountedFrameMap+slot,x
        clc
        adc #$90
        sta SCREEN_A+$3f8+slot
        sta SCREEN_B+$3f8+slot
    }
    inc frameCounter
    bne !counted+
    inc frameCounter+1
!counted:
frameComplete:
    NextIRQ(146, irqFence)
    jmp irqReturn

irqFence:
    SelectBand(0)
    lda #1
    sta $d019
worldDisplayReady:
    NextIRQ(178, irqRoad)
    jmp irqReturn

irqRoad:
    SelectBand(1)
    lda #1
    sta $d019
    lda skyPhase
    beq !done+
    lda pairCounter
    and #1
    bne !done+
    ldx #0
    lda #2
    jsr requestStep
!done:
    NextIRQ(210, irqFront)
    jmp irqReturn

irqFront:
    SelectBand(2)
    lda #1
    sta $d019
    lda #$7f
    sta $d01b
    lda skyPhase
    beq !done+
    ldx #1
    lda #2
    jsr requestStep
!done:
    NextIRQ(252, irqBottom)
    jmp irqReturn

irqBottom:
    lda #1
    sta $d019
    lda skyPhase
    beq !done+
    ldx #2
    lda #4
    jsr requestStep
!done:
    NextIRQ(40, irqHeader)
irqReturn:
    pla
    tay
    pla
    tax
    pla
    sta $01
    pla
    rti

requestStep:
    sta stepPixels
    lda paused
    bne !done+
    lda pendingCommits,x
    bne !stall+
    lda fineValues,x
    sec
    sbc stepPixels
    bmi !coarse+
    sta fineValues,x
    ora #$10
    sta fineRegisterValues,x
    ora skyPhase
    sta displayRegisterValues,x
    rts
!coarse:
    clc
    adc #8
    sta pendingFine,x
    lda jobStates,x
    cmp #1
    bne !stall+
    lda #2
    sta jobStates,x
    lda #1
    sta pendingCommits,x
    sta pendingMask
!done:
    rts
!stall:
    inc stallCounts,x
    rts

readSpace:
    lda #$7f
    sta $dc00
    lda $dc01
    and #$10
    bne !released+
    lda spaceHeld
    bne !done+
    lda #1
    sta spaceHeld
    lda paused
    eor #1
    sta paused
    beq !running+
    lda #11
!running:
    sta $d020
    jmp !done+
!released:
    lda #0
    sta spaceHeld
!done:
    lda #$ff
    sta $dc00
    rts

nmi:
    rti

commitFence:
    CommitAttributes(12, 4)
    rts
commitRoad:
    CommitAttributes(16, 4)
    rts
commitFront:
    CommitAttributes(20, 5)
    rts

frameCounter: .word 0
motionCounter: .byte 0
animationFrame: .byte 0
skyPhase: .byte 1
pairCounter: .byte 0
paused: .byte 0
spaceHeld: .byte 0
nextRaster: .byte 40
fineValues:
fineBack: .byte 0
fineMiddle: .byte 0
fineNear: .byte 0
fineRegisterValues: .byte $10, $10, $10
displayRegisterValues:
    .byte $10
roadDisplayFine: .byte $10
    .byte $10
coarseValues:
coarseBack: .byte 0
coarseMiddle: .byte 0
coarseNear: .byte 0
activeBuffers:
bufferBack: .byte 0
bufferMiddle: .byte 0
bufferNear: .byte 0
bitmapRegisters: .byte $80, $80, $80
jobStates:
readyBack: .byte 0
readyMiddle: .byte 0
readyNear: .byte 0
jobPhases: .fill 3, 0
routineBases: .byte 0, 12, 24
routineBasesB: .byte 6, 18, 30
jobColumns: .fill 3, 0
jobColumnsB: .fill 3, 0
pendingCommits: .fill 3, 0
pendingMask: .byte 0
pendingFine: .fill 3, 0
stallCounts: .fill 3, 0
workBand: .byte 0
scheduleIndex: .byte 0
routineIndex: .byte 0
copyOffset: .byte 0
copyColumn: .byte 0
copyColumns: .byte 2
copyAvailableLines: .byte 0
copyRaster: .byte 0
stepPixels: .byte 0
phaseBankValues: .byte 2, 0
skyScrollValues: .byte $18, $19
bitmapValues: .byte $80, $88
workSchedule: .byte 2, 1, 2, 0, 2, 1, 2
bandRoutineBase: .byte 0, 12, 24
copyFourGuardLines: .byte 30, 30, 38
commitLow: .byte <commitFence, <commitRoad, <commitFront
commitHigh: .byte >commitFence, >commitRoad, >commitFront
attributeWrapA: .fill 5, 0
attributeWrapB: .fill 5, 0
attributeWrapColor: .fill 5, 0
worldColumnPeriods: .byte 40, 40, 40
.align $100
columnRoutineOffsets:
    .fill 40, i < 32 ? 0 : i < 38 ? 1 : 2
columnByteOffsets:
    .fill 40, i == 38 ? 0 : (i & 31) * 8

.assert "Runtime must remain below staged phase-B bitmap", * < $2000, true

.macro NextIRQ(line, handler) {
    lda #<handler
    sta irqDispatch+1
    lda #>handler
    sta irqDispatch+2
    lda #line
    sta nextRaster
    sta $d012
}

.macro SelectBand(band) {
    // Change bitmap/fine scroll in the preceding right border, after its final fetch.
    .if (band != 2) {
        // With the rider raised, fence and road have actor DMA; front does not.
        ldy bitmapRegisters+band
    } else {
        ldx activeBuffers+band
        lda bitmapValues,x
        tay
    }
    .if (band == 1) {
        ldx roadDisplayFine
    } else {
        lda fineValues+band
        clc
        adc skyPhase
        ora #$10
        tax
        nop
    }
    sty $d018
    stx $d016
}

.macro CommitAttributes(firstRow, rows) {
    .for (var row = 0; row < rows; row++) {
        lda SCREEN_A + (firstRow + row) * 40
        sta attributeWrapA+row
        lda SCREEN_B + (firstRow + row) * 40
        sta attributeWrapB+row
        lda $d800 + (firstRow + row) * 40
        and #15
        sta attributeWrapColor+row
    }
    ldx #0
!shift:
    .for (var row = 0; row < rows; row++) {
        lda SCREEN_A + (firstRow + row) * 40 + 1,x
        sta SCREEN_A + (firstRow + row) * 40,x
        lda SCREEN_B + (firstRow + row) * 40 + 1,x
        sta SCREEN_B + (firstRow + row) * 40,x
        lda $d800 + (firstRow + row) * 40 + 1,x
        sta $d800 + (firstRow + row) * 40,x
    }
    inx
    cpx #39
    bne !shift-
    .for (var row = 0; row < rows; row++) {
        lda attributeWrapA+row
        sta SCREEN_A + (firstRow + row) * 40 + 39
        lda attributeWrapB+row
        sta SCREEN_B + (firstRow + row) * 40 + 39
        lda attributeWrapColor+row
        sta $d800 + (firstRow + row) * 40 + 39
    }
}

#import "rimrunner-parallax-assets.asm"
