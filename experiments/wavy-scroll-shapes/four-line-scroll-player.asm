// PAL two-phase four-line bitmap scroller. Each VIC bank has its own
// bitmap and pair of screen matrices. The phases share hardware Color RAM.
#import "four-line-scroll-generated.asm"

.var imageA = LoadBinary(cmdLineVars.get("bitmapA"))
.var imageB = LoadBinary(cmdLineVars.get("bitmapB"))
.var compressedColors = LoadBinary(cmdLineVars.get("rowColors"))
.const startOffset = cmdLineVars.containsKey("startOffset") ? cmdLineVars.get("startOffset").asNumber() : 0
.const screenTopA = $4000
.const screenBottomA = $4400
.const bitmapRamA = $6000
.const screenTopB = $8000
.const screenBottomB = $8400
.const bitmapRamB = $a000
.const colorRam = $d800
.const screenTopRegister = $08
.const screenBottomRegister = $18
.const normalD011 = $3b
.const lateD011 = $3f
.const palCyclesPerLine = 63
.const palLines = 312
.const naturalBadlineStall = 43
.const lateBadlineStall = 40
.const firstDelay = (55 - 48) * palCyclesPerLine + (10 - 3) - naturalBadlineStall - 8
.const groupDelay = 8 * palCyclesPerLine - naturalBadlineStall - lateBadlineStall - 24
.const skippedGroupDelay = 8 * palCyclesPerLine - naturalBadlineStall
.const rowBytes = 1000
.const colorData = $e000
.const wrapOffset = rowBytes - columnsA
.const scrollPeriod = wrapOffset + 1
.const lookupHalf = floor((columnsA + 1 + scrollBOffset) / 2) + 1
.const lookupStride = 2 * lookupHalf
.const lookupSize = rowCount * lookupStride
.const readPtr = $f7
.const packedOffset = $f9
.const lookupRow = $fb
.const sourceParity = $fc
.const lzDestination = $f9
.const lzMatch = $fb
.const lzChunk = $fd
.const lzChunkEnd = $fe
.const lzChunkCount = 4
.const rasterJobVector = $f0
.const rasterPlanBytes = rasterPacked ? rasterTableStride * (1 + rasterMapFieldsA + rasterMapFieldsB) : 0
.const rasterPlanInTail = rasterPacked && rasterPlanBytes <= screenTopB - bitmapRamA - 8000
.label rasterPlanTable = rasterPlanInTail ? bitmapRamA + 8000 : rasterPlanCodeTable
.const firstRasterA = phaseAGroups.size() > 0 ? 46 + 8 * phaseAGroups.get(0) : 51
.const firstRasterB = phaseBGroups.size() > 0 ? 46 + 8 * phaseBGroups.get(0) : 51

.function sameRasterGroups(a, b) {
    .if (a.size() != b.size()) { .return false }
    .for (var i = 0; i < a.size(); i++) {
        .if (a.get(i) != b.get(i)) { .return false }
    }
    .return true
}
.const separateKernelB = phaseBGroups.size() > 0 && !sameRasterGroups(phaseAGroups, phaseBGroups)

.errorif imageA.getSize() != 8000 || imageB.getSize() != 8000, "Expected two 8000-byte bitmaps"
.errorif colorData + rowCount * packedRowBytes > $fffa, "Packed color streams overlap interrupt vectors"
.errorif floor(wrapOffset / 2) + lookupHalf > packedRowBytes, "Packed color row lacks wrap padding"
.errorif startOffset != floor(startOffset) || startOffset < 0 || startOffset > wrapOffset, "Start offset outside the scroll loop"
.errorif scrollBOffset < 0 || scrollBOffset > 1, "Expected at most one leading color column for phase B"
.errorif colorCyclesA > (palLines - 256 + min(51, firstRasterA)) * palCyclesPerLine - 180, "Phase A Color RAM writer exceeds vblank"
.errorif colorCyclesB > (palLines - 256 + min(51, firstRasterB)) * palCyclesPerLine - 180, "Phase B Color RAM writer exceeds vblank"
.errorif rasterPlanBytes > 256, "Raster work plans must share a single page"
.errorif rasterPacked && (rasterWorkDelayCycles != firstDelay || rasterWorkDelayCycles != groupDelay), "Packed jobs must match both raster delays"

// DEX/BNE has one extra cycle per taken branch when it crosses a page.
.macro WaitCycles(cycles) {
    .var remaining = cycles
    .while (remaining >= 16) {
        .var low = * & $ff
        .var crosses = low >= 251 && low <= 253
        .var loopCycles = crosses ? 6 : 5
        .var overhead = crosses ? 0 : 1
        .var iterations = min(255, floor((remaining - overhead) / loopCycles))
        .if (remaining - iterations * loopCycles - overhead == 1) {
            .eval iterations -= 1
        }
        ldx #iterations
    !delay:
        dex
        bne !delay-
        .eval remaining -= iterations * loopCycles + overhead
    }
    .if ((remaining & 1) != 0) {
        bit $02
        .eval remaining -= 3
    }
    .fill remaining / 2, $ea
}

.macro RasterKernel(groups) {
    .var slot = 0
    txs
    ldx #8
!delay:
    dex
    bne !delay-
    bit $00
    lda $d012
    cmp $d012
    beq * + 2
    .if (groups.size() != 0) {
        .if (rasterPacked) {
            ldx #2 * slot
            jsr rasterDispatch
            .eval slot += 1
        } else {
            WaitCycles(firstDelay)
        }
    }

    .for (var i = 0; i < groups.size(); i++) {
        lda #screenBottomRegister
        sta $d018
        // The late fetch changes the matrix after RC has been sampled.
        lda #lateD011
        sta $d011
        lda #normalD011
        sta $d011
        lda #screenTopRegister
        sta $d018
        .if (i + 1 < groups.size()) {
            .var skipped = groups.get(i + 1) - groups.get(i) - 1
            .if (rasterPacked && skipped == 0) {
                ldx #2 * slot
                jsr rasterDispatch
                .eval slot += 1
            } else {
                WaitCycles(groupDelay + skipped * skippedGroupDelay)
            }
        }
    }
    jmp finishRaster
}

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
    sta $d020
    sta $d021
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
    lda #screenTopRegister
    sta $d018
    lda #$18
    sta $d016

    ldx #0
    lda #0
clearColor:
    .for (var page = 0; page < 4; page++) {
        sta colorRam + page*$100,x
    }
    inx
    bne clearColor

    jsr decompressColors
    jsr prepareLookup
    jsr writeScreenA
    jsr writeColorA
    jsr selectA
    // Start in the high-raster interval so the first visible field is A.
!startupVisible:
    bit $d011
    bmi !startupVisible-
!startupVblank:
    bit $d011
    bpl !startupVblank-
    jsr armPhase
    lda #1
    sta $d01a
    cli

scroll:
    .if (rasterPacked) {
        // A's raster job writes B's inactive matrices using lookup n.
        jsr preserveColorB
    !waitBScreen:
        lda rasterMapCursor
        cmp #rasterMapFieldsA
        bcc !waitBScreen-
        inc phaseReady
        jsr advanceOffset
        jsr prepareLookup
        inc lookupReady
        .if (fieldsPerAdvance == 3) {
            // If the table became ready after vblank, phase B can still start
            // this field's raster work while its first IRQ is far enough away.
            lda currentPhase
            beq !waitB+
            lda rasterJobActive
            bne !waitB+
            bit $d011
            bmi !rearm+
            lda $d012
            cmp #firstRasterB - 2
            bcs !waitB+
        !rearm:
            jsr selectRasterPlan
        }
    !waitB:
        lda currentPhase
        beq !waitB-
    !waitAScreen:
        lda rasterMapCursor
        cmp #rasterMapFieldsB
        bcc !waitAScreen-
    } else {
        // Prepare the inactive phase while the displayed phase owns VIC RAM.
        // Both phases read the same color window before advancing one column.
        jsr writeScreenB
        jsr preserveColorB
        inc phaseReady
        // B's saved Color RAM lookup lets preparation for the following A
        // begin immediately, while the current A still occupies the screen.
        jsr advanceOffset
        jsr prepareLookup
    !waitB:
        lda currentPhase
        beq !waitB-
        jsr writeScreenA
    }
    inc phaseReady
!waitA:
    lda currentPhase
    bne !waitA-
    jmp scroll

writeScreenA:
    .if (rasterPacked) {
        CallPackedScreenA()
        rts
    } else {
        jsr writeScreenTopA
        jmp writeScreenBottomA
    }

writeScreenB:
    .if (!rasterPacked) {
        jsr writeScreenTopB
        jmp writeScreenBottomB
    }

preserveColorB:
    .if (sparseColorBLookup) {
        PreserveSparseColorB()
    } else {
        .if (lookupSize >= 256) {
            ldx #0
        !pageByte:
            .for (var page = 0; page < floor(lookupSize / 256); page++) {
                lda waveLutLow + page * 256,x
                sta waveLutColorB + page * 256,x
            }
            inx
            bne !pageByte-
        }
        .if ((lookupSize & $ff) != 0) {
            .const pageOffset = lookupSize & $ff00
            ldx #(lookupSize & $ff) - 1
        !tailByte:
            lda waveLutLow + pageOffset,x
            sta waveLutColorB + pageOffset,x
            dex
            cpx #$ff
            bne !tailByte-
        }
    }
    rts

selectA:
    lda $dd00
    and #$fc
    ora #2
    sta $dd00
    lda #0
    sta currentPhase
    .if (rasterPacked) {
        sta lookupReady
    }
    lda nextOffset
    sta currentOffset
    lda nextOffset+1
    sta currentOffset+1
    rts

selectB:
    lda $dd00
    and #$fc
    ora #1
    sta $dd00
    lda #1
    sta currentPhase
    .if (scrollBOffset != 0) {
        AdvanceScrollOffset(currentOffset, scrollBOffset)
    }
    rts

// The prepared base offset and phase B's displayed offset use the same
// circular color stream. Both increments are shorter than one loop.
.macro AdvanceScrollOffset(offset, amount) {
    clc
    lda offset
    adc #amount
    sta offset
    lda offset+1
    adc #0
    sta offset+1
    cmp #>scrollPeriod
    bcc !done+
    bne !wrap+
    lda offset
    cmp #<scrollPeriod
    bcc !done+
!wrap:
    sec
    lda offset
    sbc #<scrollPeriod
    sta offset
    lda offset+1
    sbc #>scrollPeriod
    sta offset+1
!done:
}

advanceOffset:
    AdvanceScrollOffset(nextOffset, scrollColumnsPerPair)
    rts

decompressColors:
    lda #$ff
    sta lzChunk
    jsr nextLzChunk
    lda #<colorData
    sta lzDestination
    lda #>colorData
    sta lzDestination+1
!token:
    jsr readLzByte
    beq !complete+
    cmp #$80
    bcc !literal+
    sbc #125
    tax
    jsr readLzByte
    sta lzMatch
    jsr readLzByte
    sta lzMatch+1
!match:
    lda (lzMatch),y
    jsr writeLzByte
    inc lzMatch
    bne !next+
    inc lzMatch+1
!next:
    dex
    bne !match-
    beq !token-
!literal:
    tax
!copy:
    jsr readLzByte
    jsr writeLzByte
    dex
    bne !copy-
    beq !token-
!complete:
    rts

readLzByte:
    ldy #0
    lda (readPtr),y
    pha
    inc readPtr
    bne !checkEnd+
    inc readPtr+1
!checkEnd:
    lda readPtr
    cmp lzChunkEnd
    bne !done+
    lda readPtr+1
    cmp lzChunkEnd+1
    bne !done+
    jsr nextLzChunk
!done:
    pla
    cmp #0
    rts

// A token can cross a gap. Move to the next occupied chunk at the byte
// boundary while preserving X, which counts an unfinished literal run.
nextLzChunk:
    txa
    pha
!next:
    inc lzChunk
    ldx lzChunk
    cpx #lzChunkCount
    beq !done+
    lda colorChunkStartsLo,x
    sta readPtr
    lda colorChunkStartsHi,x
    sta readPtr+1
    lda colorChunkEndsLo,x
    sta lzChunkEnd
    cmp readPtr
    bne !positioned+
    lda colorChunkEndsHi,x
    cmp readPtr+1
    beq !next-
!positioned:
    lda colorChunkEndsHi,x
    sta lzChunkEnd+1
!done:
    pla
    tax
    rts

writeLzByte:
    sta (lzDestination),y
    inc lzDestination
    bne !done+
    inc lzDestination+1
!done:
    rts

// Packed input stores the earlier logical column in the low nibble.
// Separate even and odd destinations let one Y index drive both halves.
.macro SetLookupDestinations(highLabel, lowLabel, evenLo, evenHi, oddLo, oddHi) {
    lda evenLo,x
    sta lowLabel+1
    lda evenHi,x
    sta lowLabel+2
    lda oddLo,x
    sta highLabel+1
    lda oddHi,x
    sta highLabel+2
}

prepareLookup:
    lda nextOffset+1
    lsr
    sta packedOffset+1
    lda nextOffset
    ror
    sta packedOffset
    lda #0
    sta lookupRow
    lda nextOffset
    and #1
    sta sourceParity
!loadRow:
    ldx lookupRow
    clc
    lda packedRowsLo,x
    adc packedOffset
    sta readPtr
    lda packedRowsHi,x
    adc packedOffset+1
    sta readPtr+1

    lda sourceParity
    bne !odd+
    SetLookupDestinations(storeOddLow, storeEvenLow, lowEvenLo, lowEvenHi, lowOddLo, lowOddHi)
    SetLookupDestinations(storeOddHigh, storeEvenHigh, highEvenLo, highEvenHi, highOddLo, highOddHi)
    jmp !decode+
!odd:
    // The leading high nibble is logical column zero. Low nibbles begin
    // at column one in the next packed byte, where Y is already one.
    SetLookupDestinations(storeOddLow, storeEvenLow, lowShiftLo, lowShiftHi, lowEvenLo, lowEvenHi)
    SetLookupDestinations(storeOddHigh, storeEvenHigh, highShiftLo, highShiftHi, highEvenLo, highEvenHi)
    // Below, storeEven* receives the source low nibble and storeOdd* the
    // high nibble, independent of the destination parity.
!decode:
    ldy #0
!packedByte:
    lax (readPtr),y
    and #$0f
storeEvenLow:
    sta $ffff,y
    lda lowShifted,x
storeEvenHigh:
    sta $ffff,y
    lda highNibble,x
storeOddLow:
    sta $ffff,y
    txa
    and #$f0
storeOddHigh:
    sta $ffff,y
    iny
    cpy #lookupHalf
    bne !packedByte-

    inc lookupRow
    lda lookupRow
    cmp #rowCount
    beq !done+
    jmp !loadRow-
!done:
    rts

armPhase:
    .if (rasterPacked) {
        jsr selectRasterPlan
    }
    lda currentPhase
    bne !phaseB+
    .if (phaseAGroups.size() == 0) {
        jmp armVblank
    } else {
        lda #<irqStableA
        ldx #>irqStableA
        ldy #firstRasterA
        jmp armRaster
    }
!phaseB:
    .if (phaseBGroups.size() == 0) {
        jmp armVblank
    } else {
        lda #<(separateKernelB ? irqStableB : irqStableA)
        ldx #>(separateKernelB ? irqStableB : irqStableA)
        ldy #firstRasterB
    }
armRaster:
    sta stableLow+1
    stx stableHigh+1
    sty $d012
    lda #normalD011
    sta $d011
    lda #<irqFirst
    sta $fffe
    lda #>irqFirst
    sta $ffff
    lda #1
    sta $d019
    rts

selectRasterPlan:
    .if (rasterPacked) {
        lda #0
        sta rasterJobActive
        ldx rasterMapCursor
        lda currentPhase
        bne !phaseB+
        cpx #rasterMapFieldsA
        bcs !idle+
        lda rasterPlansA,x
        jmp !work+
    !phaseB:
        lda lookupReady
        beq !idle+
        cpx #rasterMapFieldsB
        bcs !idle+
        lda rasterPlansB,x
    !work:
        inc rasterJobActive
        jmp !set+
    !idle:
        lda #<rasterPlanTable
    !set:
        sta rasterDispatchLo+1
        clc
        adc #1
        sta rasterDispatchHi+1
        rts
    }

rasterDispatch:
rasterDispatchLo:
    .if (rasterPacked) {
        lda rasterPlanTable,x
        sta rasterJobVector
    }
rasterDispatchHi:
    .if (rasterPacked) {
        lda rasterPlanTable+1,x
        sta rasterJobVector+1
        jmp (rasterJobVector)
    }

rasterIdleChunk:
    .if (rasterPacked) {
        WaitCycles(firstDelay - rasterChunkEntryCycles - rasterChunkExitCycles)
        rts
    }

armVblank:
    lda #<irqVblank
    sta $fffe
    lda #>irqVblank
    sta $ffff
    lda #0
    sta $d012
    lda #normalD011 | $80
    sta $d011
    lda #1
    sta $d019
    rts

irqFirst:
    pha
    txa
    pha
stableLow:
    lda #0
    sta $fffe
stableHigh:
    lda #0
    sta $ffff
    inc $d012
    lda #1
    sta $d019
    tsx
    cli
    .fill 20, $ea

.if (phaseAGroups.size() > 0) {
    .align $100
}
irqStableA:
    .if (phaseAGroups.size() > 0) {
        RasterKernel(phaseAGroups)
    }

.if (separateKernelB) {
    .align $100
}
irqStableB:
    .if (separateKernelB) {
        RasterKernel(phaseBGroups)
    }

finishRaster:
    .if (rasterPacked) {
        lda rasterJobActive
        beq !idle+
        inc rasterMapCursor
    !idle:
    }
    jsr armVblank
    pla
    tax
    pla
    rti

irqVblank:
    pha
    txa
    pha
    tya
    pha
frameComplete:
    dec framesLeft
    bne !resume+
    lda phaseReady
    beq !missed+
    lda currentPhase
    beq !nextB+
    jsr writeColorA
    jsr selectA
    jmp !reset+
!nextB:
    jsr writeColorB
    jsr selectB
!reset:
    lda #0
    sta phaseReady
    .if (rasterPacked) {
        sta rasterMapCursor
    }
    lda #fieldsPerAdvance
    sta framesLeft
    bne !resume+
!missed:
    inc missedDeadline
    inc framesLeft
!resume:
    jsr armPhase
    pla
    tay
    pla
    tax
    pla
    rti

nmi:
    rti

currentPhase:    .byte 0
currentOffset:   .word startOffset
nextOffset:      .word startOffset
phaseReady:      .byte 0
framesLeft:      .byte fieldsPerAdvance
missedDeadline:  .byte 0
rasterMapCursor:
    .if (rasterPacked) { .byte 0 }
lookupReady:
    .if (rasterPacked) { .byte 0 }
rasterJobActive:
    .if (rasterPacked) { .byte 0 }

rasterPlansA:
    .if (rasterPacked) {
        .fill rasterMapFieldsA, <(rasterPlanTable + (1 + i) * rasterTableStride)
    }
rasterPlansB:
    .if (rasterPacked) {
        .fill rasterMapFieldsB, <(rasterPlanTable + (1 + rasterMapFieldsA + i) * rasterTableStride)
    }

.if (rasterPacked && !rasterPlanInTail) {
    .align $100
}
rasterPlanCodeTable:
    .if (rasterPacked && !rasterPlanInTail) {
        EmitRasterPlanTables()
        .errorif * - rasterPlanTable != rasterPlanBytes, "Wrong raster work plan size"
    }

packedRowsLo: .fill rowCount, <(colorData + i * packedRowBytes)
packedRowsHi: .fill rowCount, >(colorData + i * packedRowBytes)
lowEvenLo:    .fill rowCount, <(waveLutLow + i * lookupStride)
lowEvenHi:    .fill rowCount, >(waveLutLow + i * lookupStride)
lowOddLo:     .fill rowCount, <(waveLutLow + i * lookupStride + lookupHalf)
lowOddHi:     .fill rowCount, >(waveLutLow + i * lookupStride + lookupHalf)
lowShiftLo:   .fill rowCount, <(waveLutLow + i * lookupStride + lookupHalf - 1)
lowShiftHi:   .fill rowCount, >(waveLutLow + i * lookupStride + lookupHalf - 1)
highEvenLo:   .fill rowCount, <(waveLutHigh + i * lookupStride)
highEvenHi:   .fill rowCount, >(waveLutHigh + i * lookupStride)
highOddLo:    .fill rowCount, <(waveLutHigh + i * lookupStride + lookupHalf)
highOddHi:    .fill rowCount, >(waveLutHigh + i * lookupStride + lookupHalf)
highShiftLo:  .fill rowCount, <(waveLutHigh + i * lookupStride + lookupHalf - 1)
highShiftHi:  .fill rowCount, >(waveLutHigh + i * lookupStride + lookupHalf - 1)
colorChunkStartsLo: .byte <colorChunk0, <colorChunk1, <colorChunk2, <colorChunk3
colorChunkStartsHi: .byte >colorChunk0, >colorChunk1, >colorChunk2, >colorChunk3
colorChunkEndsLo:   .byte <colorChunk0End, <colorChunk1End, <colorChunk2End, <colorChunk3End
colorChunkEndsHi:   .byte >colorChunk0End, >colorChunk1End, >colorChunk2End, >colorChunk3End

// The stream is read only during startup. Pack it into the unused ranges
// after the resident code and lookup tables, without displacing VIC data.
.var colorStreamOffset = 0
.macro StoreColorChunk(limit) {
    .var count = min(limit - *, compressedColors.getSize() - colorStreamOffset)
    .fill count, compressedColors.get(colorStreamOffset + i)
    .eval colorStreamOffset += count
}

.align $100
lowShifted: .fill 256, (i & $f) << 4
highNibble: .fill 256, i >> 4
writeScreenTopA:
    WriteScreenTopA()
    rts
writeScreenTopB:
    WriteScreenTopB()
    rts
writeColorB:
    WriteColorB()
    rts
.errorif * > screenTopA, "Player and color writers overlap VIC bank A"
colorChunk0:
    StoreColorChunk(screenTopA)
colorChunk0End:

* = screenTopA "Screen A top"
    .fill $400, 0
* = screenBottomA "Screen A bottom"
    .fill $400, 0
writeScreenBottomA:
    WriteScreenBottomA()
    rts
waveLutLow: .fill lookupSize, 0
.errorif * > bitmapRamA, "Phase A screen writer and lookup table overlap its bitmap"
colorChunk1:
    StoreColorChunk(bitmapRamA)
colorChunk1End:

* = bitmapRamA "Bitmap A"
    .fill imageA.getSize(), imageA.get(i)
    .if (rasterPlanInTail) {
        EmitRasterPlanTables()
        .errorif * - rasterPlanTable != rasterPlanBytes, "Wrong raster work plan size"
    }

* = screenTopB "Screen B top"
    .fill $400, 0
* = screenBottomB "Screen B bottom"
    .fill $400, 0
writeScreenBottomB:
    WriteScreenBottomB()
    rts
waveLutHigh: .fill lookupSize, 0
.errorif * > bitmapRamB, "Phase B screen writer and lookup table overlap its bitmap"
colorChunk2:
    StoreColorChunk(bitmapRamB)
colorChunk2End:

* = bitmapRamB "Bitmap B"
    .fill imageB.getSize(), imageB.get(i)
writeColorA:
    WriteColorA()
    rts
waveLutColorB: .fill colorBLookupSize, 0
colorBIndices:
    EmitSparseColorBIndices()
.errorif * > $d000, "Color RAM writer and backup lookup overlap I/O"
colorChunk3:
    StoreColorChunk($d000)
colorChunk3End:
.errorif colorStreamOffset != compressedColors.getSize(), "Compressed color rows exceed the RAM available between VIC data and player code"
