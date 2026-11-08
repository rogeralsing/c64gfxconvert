// Stock PAL C64 MCI sine warp. Startup relocates a payload loaded below I/O,
// generates the copy kernels, and builds both initial bitmaps before display.
.var sourceAData = LoadBinary("source-a.bin")
.var sourceBData = LoadBinary("source-b.bin")
.var screenAData = LoadBinary("screen-a.bin")
.var screenBData = LoadBinary("screen-b.bin")
.var colorData = LoadBinary("colors.bin")
.var backgroundData = LoadBinary("background.bin")
.var offsetData = LoadBinary("frame-offsets.bin")
.var geometryData = LoadBinary("row-maps.rle")

.const sourceA = $8000
.const sourceB = sourceA + 12480
.const frameOffsets = sourceB + 12480
.const geometry = frameOffsets + 480
.const bitmapA = $2000
.const bitmapB = $6000
.const copyCodeA = $0800
.const copyCodeB = $4800
.const copyALow = $7f40
.const copyAHigh = copyALow + 25
.const copyBLow = copyAHigh + 25
.const copyBHigh = copyBLow + 25
.const changedSources = $3f40
.const changedY = changedSources + 40
.const changedTile = changedY + 40
.const rowMap0 = $0200
.const rowMap1 = $0300
.const sourcePointer = $f0
.const destinationPointer = $f2
.const codePointer = $f4
.const lowTablePointer = $f6
.const highTablePointer = $f8
.const rlePointer = $fa
.const bytesRemaining = $fc

.macro Relocate(from, to, length) {
    lda #<(from + length - 1)
    sta sourcePointer
    lda #>(from + length - 1)
    sta sourcePointer+1
    lda #<(to + length - 1)
    sta destinationPointer
    lda #>(to + length - 1)
    sta destinationPointer+1
    lda #<length
    sta bytesRemaining
    lda #>length
    sta bytesRemaining+1
    jsr relocateBackward
}

BasicUpstart2(bootstrap)

bootstrap:
    sei
    cld
    lda #$2f
    sta $00
    lda #$37
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    lda #$0b
    sta $d011
    lda #$35
    sta $01
    lda #<bootstrapNmi
    sta $fffa
    lda #>bootstrapNmi
    sta $fffb
    lda #$34
    sta $01
    // The source blob is last in the staged payload. Backward copying permits
    // its higher destination to overlap that blob without losing input bytes.
    Relocate(sourcePayload, sourceA, 24960)
    Relocate(geometryPayload, frameOffsets, 480 + geometryData.getSize())
    Relocate(runtimePayload, runtimeStart, runtimePayloadEnd-runtimePayload)
    Relocate(screenAPayload, $0400, 1000)
    Relocate(screenBPayload, $4400, 1000)
    lda #$35
    sta $01
    Relocate(colorPayload, $d800, 1000)
    jmp runtimeStart

relocateBackward:
    ldy #0
relocateByte:
    lda (sourcePointer),y
    sta (destinationPointer),y
    lda sourcePointer
    bne sourceLowReady
    dec sourcePointer+1
sourceLowReady:
    dec sourcePointer
    lda destinationPointer
    bne destinationLowReady
    dec destinationPointer+1
destinationLowReady:
    dec destinationPointer
    lda bytesRemaining
    bne remainingLowReady
    dec bytesRemaining+1
remainingLowReady:
    dec bytesRemaining
    lda bytesRemaining
    ora bytesRemaining+1
    bne relocateByte
    rts
bootstrapNmi:
    rti

runtimePayload:
.pseudopc $f500 {
runtimeStart:
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda #$34
    sta $01
    lda #<sourceA
    sta sourcePointer
    lda #>sourceA
    sta sourcePointer+1
    lda #<bitmapA
    sta destinationPointer
    lda #>bitmapA
    sta destinationPointer+1
    lda #<copyCodeA
    sta codePointer
    lda #>copyCodeA
    sta codePointer+1
    lda #<copyALow
    sta lowTablePointer
    lda #>copyALow
    sta lowTablePointer+1
    lda #<copyAHigh
    sta highTablePointer
    lda #>copyAHigh
    sta highTablePointer+1
    jsr generatePhase
    lda #<sourceB
    sta sourcePointer
    lda #>sourceB
    sta sourcePointer+1
    lda #<bitmapB
    sta destinationPointer
    lda #>bitmapB
    sta destinationPointer+1
    lda #<copyCodeB
    sta codePointer
    lda #>copyCodeB
    sta codePointer+1
    lda #<copyBLow
    sta lowTablePointer
    lda #<copyBHigh
    sta highTablePointer
    jsr generatePhase

    ldx #0
initializeMaps:
    txa
    and #15
    clc
    adc #4
    sta rowMap0,x
    sta rowMap1,x
    inx
    cpx #200
    bne initializeMaps
    lda #<copyALow
    sta initializeReadLow+1
    lda #<copyAHigh
    sta initializeReadHigh+1
    jsr initializeBitmap
    lda #<copyBLow
    sta initializeReadLow+1
    lda #<copyBHigh
    sta initializeReadHigh+1
    jsr initializeBitmap
    lda #$35
    sta $01
    lda #0
    sta phase
    sta displayFrame
    sta changedCount
    lda #2
    sta mapPage
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    and #$fc
    ora #3
    sta $dd00
    lda #$18
    sta $d016
    sta $d018
    lda #backgroundData.get(0)
    sta $d020
    sta $d021
    lda #$3b
    sta $d011
startupSync:
    bit $d011
    bpl startupSync
    jmp phaseAWork

phaseAWork:
    // A(k) displays while B(k-1) receives the already prepared k transition.
    lda #<copyBLow
    sta copyReadLow+1
    lda #<copyBHigh
    sta copyReadHigh+1
    jsr copyChangedRows
    // The old transition is consumed. Reuse its list for the next frame.
    jsr startNextMap
    lda #100
    sta decodeLimit+1
    jsr decodeRows
    jmp waitFrameStart

phaseBWork:
    // Complete k+1's map, then update A while B(k) is displayed.
    lda #200
    sta decodeLimit+1
    jsr decodeRows
    lda #<copyALow
    sta copyReadLow+1
    lda #<copyAHigh
    sta copyReadHigh+1
    jsr copyChangedRows

waitFrameStart:
    // Short zero-motion work can finish before the PAL raster wraps.
    bit $d011
    bmi waitFrameStart
waitComplete:
    bit $d011
    bpl waitComplete
frameComplete:
    // phase, displayFrame and mapPage describe the picture just completed.
    lda phase
    bne completedPhaseB
    lda #1
    sta phase
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    lda #$19
    sta $d016
    jmp phaseBWork
completedPhaseB:
    lda #0
    sta phase
    lda mapPage
    eor #1
    sta mapPage
    inc displayFrame
    lda displayFrame
    cmp #240
    bne frameIndexReady
    lda #0
    sta displayFrame
frameIndexReady:
    lda $dd00
    and #$fc
    ora #3
    sta $dd00
    lda #$18
    sta $d016
    jmp phaseAWork

startNextMap:
    lda #0
    sta changedCount
    sta planRow
    sta runEnd
    lda mapPage
    sta compareMap+2
    eor #1
    sta writeMap+2
    lda displayFrame
    clc
    adc #1
    cmp #240
    bne nextFrameReady
    lda #0
nextFrameReady:
    asl
    sta sourcePointer
    lda #0
    rol
    sta sourcePointer+1
    clc
    lda sourcePointer
    adc #<frameOffsets
    sta sourcePointer
    lda sourcePointer+1
    adc #>frameOffsets
    sta sourcePointer+1
    ldy #0
    lda (sourcePointer),y
    clc
    adc #<geometry
    sta rlePointer
    iny
    lda (sourcePointer),y
    adc #>geometry
    sta rlePointer+1
    rts

decodeRows:
    ldy planRow
    cpy runEnd
    bne decodeRow
readRun:
    sty planRow
    ldy #0
    lda (rlePointer),y
    sta runEnd
    iny
    lda (rlePointer),y
    clc
    adc #4
    sta addDisplacement+1
    clc
    lda rlePointer
    adc #2
    sta rlePointer
    bcc runPointerReady
    inc rlePointer+1
runPointerReady:
    ldy planRow
decodeRow:
    tya
    and #15
    clc
addDisplacement:
    adc #4
writeMap:
    sta rowMap1,y
compareMap:
    cmp rowMap0,y
    beq rowUnchanged
    ldx changedCount
    sta changedSources,x
    tya
    and #7
    sta changedY,x
    tya
    lsr
    lsr
    lsr
    sta changedTile,x
    inc changedCount
rowUnchanged:
    iny
decodeLimit:
    cpy #100
    beq decodeDone
    cpy runEnd
    bne decodeRow
    jmp readRun
decodeDone:
    sty planRow
    rts

copyChangedRows:
    lda changedCount
    beq copiesDone
    lda #$34
    sta $01
    lda #0
    sta listIndex
copyOneRow:
    ldy listIndex
    lda changedTile,y
    tax
copyReadLow:
    lda copyALow,x
    sta copyCall+1
copyReadHigh:
    lda copyAHigh,x
    sta copyCall+2
    lda changedSources,y
    tax
    lda changedY,y
    tay
copyCall:
    jsr copyCodeA
    inc listIndex
    lda listIndex
    cmp changedCount
    bne copyOneRow
    lda #$35
    sta $01
copiesDone:
    rts

initializeBitmap:
    lda #0
    sta tileIndex
    lda #4
    sta initialSourceRow
initializeTile:
    ldx tileIndex
initializeReadLow:
    lda copyALow,x
    sta initializeCall+1
initializeReadHigh:
    lda copyAHigh,x
    sta initializeCall+2
    ldx initialSourceRow
    ldy #0
initializeRow:
initializeCall:
    jsr copyCodeA
    inx
    iny
    cpy #8
    bne initializeRow
    lda initialSourceRow
    eor #8
    sta initialSourceRow
    inc tileIndex
    lda tileIndex
    cmp #25
    bne initializeTile
    rts

generatePhase:
    lda #0
    sta tileIndex
generateTile:
    ldy tileIndex
    lda codePointer
    sta (lowTablePointer),y
    lda codePointer+1
    sta (highTablePointer),y
    ldx #40
generateColumn:
    ldy #0
    lda #$bd
    sta (codePointer),y
    iny
    lda sourcePointer
    sta (codePointer),y
    iny
    lda sourcePointer+1
    sta (codePointer),y
    iny
    lda #$99
    sta (codePointer),y
    iny
    lda destinationPointer
    sta (codePointer),y
    iny
    lda destinationPointer+1
    sta (codePointer),y
    clc
    lda codePointer
    adc #6
    sta codePointer
    bcc codePointerReady
    inc codePointer+1
codePointerReady:
    clc
    lda sourcePointer
    adc #24
    sta sourcePointer
    bcc sourcePointerReady
    inc sourcePointer+1
sourcePointerReady:
    clc
    lda destinationPointer
    adc #8
    sta destinationPointer
    bcc bitmapPointerReady
    inc destinationPointer+1
bitmapPointerReady:
    dex
    bne generateColumn
    ldy #0
    lda #$60
    sta (codePointer),y
    inc codePointer
    bne generatedReturnReady
    inc codePointer+1
generatedReturnReady:
    inc tileIndex
    lda tileIndex
    and #1
    beq sourceBandReady
    // Both eight-line output tiles read the same 24-line source band.
    sec
    lda sourcePointer
    sbc #<960
    sta sourcePointer
    lda sourcePointer+1
    sbc #>960
    sta sourcePointer+1
sourceBandReady:
    lda tileIndex
    cmp #25
    bne generateTile
    rts

nmi:
    rti
phase: .byte 0
displayFrame: .byte 0
mapPage: .byte 2
changedCount: .byte 0
listIndex: .byte 0
planRow: .byte 0
runEnd: .byte 0
tileIndex: .byte 0
initialSourceRow: .byte 4
runtimeEnd:
}
runtimePayloadEnd:

geometryPayload:
    .fill offsetData.getSize(), offsetData.get(i)
    .fill geometryData.getSize(), geometryData.get(i)
screenAPayload:
    .fill 1000, screenAData.get(i)
screenBPayload:
    .fill 1000, screenBData.get(i)
colorPayload:
    .fill 1000, colorData.get(i)
sourcePayload:
    .fill 12480, sourceAData.get(i)
    .fill 12480, sourceBData.get(i)
payloadEnd:
.assert "Staged PRG loads entirely below I/O", payloadEnd <= $d000, true
.assert "Geometry stays below the runtime", geometry+geometryData.getSize() <= $f500, true
.assert "Runtime leaves NMI/IRQ vectors free", runtimeEnd <= $fffa, true
.assert "Copy A leaves its bitmap free", copyCodeA+25*241 <= bitmapA, true
.assert "Copy B leaves its bitmap free", copyCodeB+25*241 <= bitmapB, true
