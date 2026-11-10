// PAL MCI rubber wave. Extra early badlines repeat row zero of a bitmap cell.
// Both MCI phases use one deformation plan; motion advances after each pair.
.var image = LoadBinary("image.mci")

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
    sta phase
    sta motion
    sta amplitude
    sta pairTick
    lda #1
    sta amplitudeDirection
    lda #$0f
    sta $d019
    lda #$0b
    sta $d011
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    lda $dd02
    ora #3
    sta $dd02

    ldx #0
copyColors:
    lda sharedColors,x
    sta $d800,x
    lda sharedColors+$100,x
    sta $d900,x
    lda sharedColors+$200,x
    sta $da00,x
    lda sharedColors+$300,x
    sta $db00,x
    inx
    bne copyColors
    lda background
    sta $d020
    sta $d021
    lda #$08
    sta $d018
    lda #$18
    sta $d016
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    jsr preparePlan
    lda #$3b
    sta $d011
startupSync:
    bit $d011
    bpl startupSync
    jmp waitFrameStart

waitFrame:
    bit $d011
    bpl waitFrame
frameComplete:
    // The completed picture's phase, amplitude and repeatCounts remain visible here.
    lda #$3b
    sta $d011
    lda phase
    eor #1
    sta phase
    tax
    lda $dd00
    and #$fc
    ora bankBits,x
    sta $dd00
    lda scrollValues,x
    sta $d016
    cpx #0
    bne waitFrameStart
    inc motion
    inc pairTick
    lda pairTick
    and #$3f
    bne updatePlan
    clc
    lda amplitude
    adc amplitudeDirection
    sta amplitude
    beq rampUp
    cmp #4
    bne updatePlan
    lda #$ff
    bne saveDirection
rampUp:
    lda #1
saveDirection:
    sta amplitudeDirection
updatePlan:
    jsr preparePlan
waitFrameStart:
    bit $d011
    bmi waitFrameStart
    lda #0
    sta cellIndex

cellLoop:
    lda cellIndex
    cmp #25
    bcs waitFrame
    ldy cellIndex
    lda cellRasters,y
    cmp #248
    bcs waitFrame
    clc
    adc #1
    sta firstLine+1
    lda repeatCounts,y
    tax
    lda entryLow,x
    sta holdDispatch+1
    lda entryHigh,x
    sta holdDispatch+2
    lda cellRasters,y
    tay
firstLine:
    ldx #52
waitCellBadline:
    cpy $d012
    bne waitCellBadline
    // Polling starts before this natural badline. DMA stretches this delay past
    // the fetch window; the first change lands late here or early next line.
    .fill 4, $ea
holdDispatch:
    jmp release

    // Each hold takes 20 CPU clocks plus 43 clocks of badline DMA: one PAL line.
    // The write selects the next raster before its cycle-14 row-counter reset.
hold4:
    lda nextScroll,x
    sta $d011
    inx
    .fill 5, $ea
hold3:
    lda nextScroll,x
    sta $d011
    inx
    .fill 5, $ea
hold2:
    lda nextScroll,x
    sta $d011
    inx
    .fill 5, $ea
hold1:
    lda nextScroll,x
    sta $d011
    inx
    .fill 5, $ea
release:
    lda lastScroll,x
    sta $d011
    // Hold this YSCROLL through source rows 1..7. The next natural badline is
    // eight lines after the last repeat and advances the matrix/color row.
    inc cellIndex
    jmp cellLoop

preparePlan:
    lda amplitude
    clc
    adc #>waveTables
    sta readWave+2
    ldx motion
    ldy #0
makeRepeats:
readWave:
    lda waveTables,x
    sta repeatCounts,y
    txa
    clc
    adc #11
    tax
    iny
    cpy #25
    bne makeRepeats
    lda #51
    sta plannedRaster
    ldy #0
makeRasters:
    lda plannedRaster
    sta cellRasters,y
    cmp #248
    bcs hiddenCell
    // The VIC accepts badlines only through raster 247. Keep every hold there.
    lda #247
    sec
    sbc plannedRaster
    cmp repeatCounts,y
    bcs countReady
    sta repeatCounts,y
countReady:
    lda plannedRaster
    clc
    adc repeatCounts,y
    adc #8
    bcs clampRaster
    cmp #248
    bcc saveRaster
    cmp #251
    bcs clampRaster
    // A next cell at 248..250 would idle at the bottom. Either move its first
    // badline to 247, or extend this cell so its normal rows cover line 250.
    sec
    sbc #247
    sta bottomAdjustment
    lda repeatCounts,y
    cmp bottomAdjustment
    bcc extendBottomCell
    sec
    sbc bottomAdjustment
    sta repeatCounts,y
    lda #247
    bne saveRaster
extendBottomCell:
    lda #243
    sec
    sbc plannedRaster
    sta repeatCounts,y
clampRaster:
    lda #248
saveRaster:
    sta plannedRaster
    jmp nextCell
hiddenCell:
    lda #0
    sta repeatCounts,y
nextCell:
    iny
    cpy #25
    bne makeRasters
    rts

nmi:
    rti
phase: .byte 0
motion: .byte 0
amplitude: .byte 0
pairTick: .byte 0
amplitudeDirection: .byte 1
cellIndex: .byte 0
plannedRaster: .byte 51
bottomAdjustment: .byte 0
bankBits: .byte 2, 1
scrollValues: .byte $18, $19
entryLow: .byte <release, <hold1, <hold2, <hold3, <hold4
entryHigh: .byte >release, >hold1, >hold2, >hold3, >hold4

.assert "Wave player must not overlap color data", * < $2000, true

* = $2000 "Shared color RAM"
sharedColors:
    .fill 1000, image.get(18434 + i)
    .fill 24, 0
background: .byte image.get(1002)
* = $2500 "Current pair deformation"
repeatCounts: .fill 25, 0
* = $2520 "Natural cell badlines"
cellRasters: .fill 25, 0
* = $2800 "Next-line scroll"
nextScroll: .fill 256, $38 | (i & 7)
* = $2900 "Release scroll"
lastScroll: .fill 256, $38 | ((i-1) & 7)
* = $3000 "Sine repeat tables"
waveTables:
    .for (var level=0; level<=4; level++) {
        .fill 256, floor((sin(toRadians(i*360/256))+1)*level/2+0.5)
    }

* = $4000 "Phase A screen"
screenA:
    .fill 1000, image.get(2 + i)
    .fill 24, 0
* = $6000 "Phase A bitmap"
bitmapA: .fill 8000, image.get(1026 + i)
* = $8000 "Phase B screen"
screenB:
    .fill 1000, image.get(17410 + i)
    .fill 24, 0
* = $a000 "Phase B bitmap"
bitmapB: .fill 8000, image.get(9218 + i)
