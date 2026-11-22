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
.const reverseLookupDecode = ((columnsA + scrollBOffset) & 1) != 0 && lookupHalf <= 128
.const windowLastStart = rowCount - activeRowCount
.const movingWindow = windowLastStart > 0

.function blankBitmapRange(image, first, end) {
    .for (var i = first; i < end; i++) {
        .if (image.get(i) != 0) { .return false }
    }
    .return true
}

// Entire blank VIC rows have zero Screen RAM and Color RAM in this build.
// Their bitmap bytes can hold CPU code and data while rendering black.
.const blankPrefixBytes = 2 * 40 * 8
.const blankSuffixBytes = 3 * 40 * 8
.function blankBitmapEdges(image) {
    .return blankBitmapRange(image, 0, blankPrefixBytes) && blankBitmapRange(image, 8000 - blankSuffixBytes, 8000)
}
.const bitmapGapLayout = movingWindow && blankBitmapEdges(imageA) && blankBitmapEdges(imageB)
.errorif useVerticalSine && (!bitmapGapLayout || windowLastStart != 8 || !rasterPacked || fieldsPerAdvance > 3), "Y sine needs a packed ribbon with nine window starts and two or three PAL fields per update"
.const bitmapPrefixBytes = bitmapGapLayout ? blankPrefixBytes : 0
.const bitmapSuffixBytes = bitmapGapLayout ? blankSuffixBytes : 0
.label bitmapBodyStartA = bitmapRamA + bitmapPrefixBytes
.label bitmapBodyStartB = bitmapRamB + bitmapPrefixBytes
.label bitmapBodyEndA = bitmapRamA + 8000 - bitmapSuffixBytes
.label bitmapBodyEndB = bitmapRamB + 8000 - bitmapSuffixBytes
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
.const rasterPlanBytes = rasterPacked ? rasterTableStride * (rasterIdleFields + rasterMapFieldsA + rasterMapFieldsB) : 0
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
.const separateKernelB = phaseBGroups.size() > 0 && (!sameRasterGroups(phaseAGroups, phaseBGroups) || !sameRasterGroups(phaseASplits, phaseBSplits))

.errorif imageA.getSize() != 8000 || imageB.getSize() != 8000, "Expected two 8000-byte bitmaps"
.errorif activeRowCount < 1 || activeRowCount > rowCount, "Active color row count is outside the bitmap"
.errorif colorData + activeRowCount * packedRowBytes > $fffa, "Packed color streams overlap interrupt vectors"
.errorif movingWindow && (windowPairsToHold < 1 || windowPairsToHold > 255), "Color window must hold for 1–255 phase pairs"
.errorif floor(wrapOffset / 2) + lookupHalf > packedRowBytes, "Packed color row lacks wrap padding"
.errorif startOffset != floor(startOffset) || startOffset < 0 || startOffset > wrapOffset, "Start offset outside the scroll loop"
.errorif scrollBOffset < 0 || scrollBOffset > 1, "Expected at most one leading color column for phase B"
.errorif colorCyclesA > (palLines - vblankRaster + min(51, firstRasterA)) * palCyclesPerLine - 180, "Phase A Color RAM writer exceeds vblank"
.errorif colorCyclesB > (palLines - vblankRaster + min(51, firstRasterB)) * palCyclesPerLine - 180, "Phase B Color RAM writer exceeds vblank"
.errorif rasterPlanBytes > 256, "Raster work plans must share a single page"
.errorif phaseASplits.size() != phaseAGroups.size() || phaseBSplits.size() != phaseBGroups.size(), "Every late fetch needs a split position"

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

.var verticalNormal = List()
.var verticalLate = List()
.for (var i = 0; i < 8; i++) { .eval verticalLate.add(List()) }

.macro RasterKernel(groups, splits) {
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
            WaitCycles(firstDelay + (splits.get(0) - 4) * palCyclesPerLine)
        }
    }

    .for (var i = 0; i < groups.size(); i++) {
        lda #screenBottomRegister
        sta $d018
        // The late fetch changes the matrix after RC has been sampled.
        .var split = splits.get(i)
        .if (useVerticalSine) { .eval verticalLate.get(split).add(* + 1) }
        lda #((normalD011 & $f8) | ((51 + split) & 7))
        sta $d011
        .if (useVerticalSine) { .eval verticalNormal.add(* + 1) }
        lda #normalD011
        sta $d011
        lda #screenTopRegister
        sta $d018
        .if (i + 1 < groups.size()) {
            .var skipped = groups.get(i + 1) - groups.get(i) - 1
            .if (rasterPacked && skipped == 0 && split < 7) {
                ldx #2 * slot
                jsr rasterDispatch
                .eval slot += 1
            } else {
                .var splitDelta = splits.get(i + 1) - split
                WaitCycles(groupDelay + skipped * skippedGroupDelay + splitDelta * palCyclesPerLine)
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
    .if (activeWindowWrites) {
        // Restore the initial zero colors after unpacking the startup stream.
        ldx #0
        txa
    !clearMatrices:
        .for (var page = 0; page < 8; page++) {
            sta screenTopA + page * $100,x
        }
        inx
        bne !clearMatrices-
    }
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
        .if (colorBLookupSize != 0) { jsr preserveColorB }
        .if (activeWindowWrites) { jsr writeScreenFringeB }
    @waitBScreen:
        lda rasterMapCursor
        cmp #rasterMapFieldsA
        bcc waitBScreen
        inc phaseReady
        jsr advanceOffset
        jsr prepareLookup
        inc lookupReady
        .if (fieldsPerAdvance <= 3) {
            // If the table became ready after vblank, phase B can still start
            // this field's raster work while its first IRQ is far enough away.
            lda currentPhase
            beq !waitB+
            lda rasterJobActive
            bne !waitB+
            bit $d011
            bmi !rearm+
            lda $d012
        @verticalRearmB:
            cmp #(firstRasterB - (fieldsPerAdvance == 2 ? 1 : 2))
            bcs !waitB+
        !rearm:
            .if (fieldsPerAdvance == 2) {
                // There is one raster pass per phase. Install both dispatch
                // operands before the first IRQ can start the kernel.
                lda rasterMapCursor
                bne !waitB+
                lda rasterPlansB
                sta rasterDispatchLo+1
                clc
                adc #1
                sta rasterDispatchHi+1
                inc rasterJobActive
            } else {
                jsr selectRasterPlan
            }
        }
    !waitB:
        lda currentPhase
        beq !waitB-
        .if (activeWindowWrites) { jsr writeScreenFringeA }
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
    .if (activeWindowWrites && fieldsPerAdvance == 2) {
        // After B's last visible raster, its screen matrices can receive
        // the next update even before the IRQ switches to A.
    !waitForBlank:
        lda currentPhase
        beq !prepareB+
        bit $d011
        bpl !waitForBlank-
    !prepareB:
        jsr writeScreenFringeB
        .if (colorBLookupSize != 0) { jsr preserveColorB }
    }
!waitA:
    lda currentPhase
    bne !waitA-
    .if (activeWindowWrites && fieldsPerAdvance == 2) {
        jmp waitBScreen
    } else {
        jmp scroll
    }

writeScreenA:
    .if (rasterPacked) {
        CallPackedScreenA()
        .if (activeWindowWrites) { jmp writeScreenFringeA } else { rts }
    } else {
        jsr writeScreenTopA
        jmp writeScreenBottomA
    }

writeScreenB:
    .if (!rasterPacked) {
        jsr writeScreenTopB
        jmp writeScreenBottomB
    }

.macro WindowBounds(previous, next) {
    ldx previous
    ldy next
    cpx next
    bcc !ready+
    ldx next
    ldy previous
!ready:
}

.if (activeWindowWrites) {
    @writeScreenFringeA:
        WindowBounds(displayWindowStart, preparedWindowStart)
        jsr screenTopFringeA
        jmp screenBottomFringeA
    @writeScreenFringeB:
        WindowBounds(previousBWindowStart, preparedWindowStart)
        jsr screenTopFringeB
        jmp screenBottomFringeB
}

.macro EmitColorBCopy() {
@preserveColorB:
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
}

.if (!bitmapGapLayout) { EmitColorBCopy() }

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
    .if (movingWindow) {
        lda preparedWindowStart
        sta displayWindowStart
        .if (useVerticalSine) { jsr updateVerticalPhase }
    }
    rts

selectB:
    lda $dd00
    and #$fc
    ora #1
    sta $dd00
    lda #1
    sta currentPhase
    .if (activeWindowWrites) {
        lda displayWindowStart
        sta previousBWindowStart
    }
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
    .if (useVerticalSine) {
        jmp gapAdvanceWindow
    } else .if (movingWindow) {
        dec windowPairsLeft
        .if (bitmapGapLayout) {
            bne !done+
            jmp gapAdvanceWindow
        !done:
        } else {
            beq mainAdvanceWindow
        }
    }
    .if (!useVerticalSine) { rts }

.macro EmitAdvanceWindow() {
    .if (useVerticalSine) {
        // The sine runs in quarter-wave rows. Keep the fine scroll with the
        // pending lookup until phase A commits both at the same VBlank.
        ldx verticalSineIndex
        inx
        cpx #verticalSineEnd - verticalSine
        bcc !sample+
        ldx #0
!sample:
        stx verticalSineIndex
        lda verticalSine,x
        tay
        and #3
        clc
        adc #3
        sta preparedVerticalScroll
        tya
        lsr
        lsr
        ldx preparedWindowStart
        sta preparedWindowStart
        cpx preparedWindowStart
        beq !done+
        bcc !clear+
        txa
        clc
        adc #activeRowCount - 1
        tax
    } else {
        // Phase B already has its colors when this runs. Prepare the new window
        // for the next A/B pair, clearing only the row that just dropped out.
        lda #windowPairsToHold
        sta windowPairsLeft
        ldx preparedWindowStart
        lda windowStep
        bmi !towardsFirst+
        inc preparedWindowStart
        cpx #windowLastStart - 1
        bne !clear+
        lda #$ff
        sta windowStep
        jmp !clear+
!towardsFirst:
        dec preparedWindowStart
        cpx #1
        bne !retireLast+
        lda #1
        sta windowStep
!retireLast:
        txa
        clc
        adc #activeRowCount - 1
        tax
    }
!clear:
    lda lowEvenLo,x
    sta clearWindowLow+1
    lda lowEvenHi,x
    sta clearWindowLow+2
    lda highEvenLo,x
    sta clearWindowHigh+1
    lda highEvenHi,x
    sta clearWindowHigh+2
    ldy #lookupStride - 1
    lda #0
!byte:
clearWindowLow:
    sta $ffff,y
clearWindowHigh:
    sta $ffff,y
    dey
    bpl !byte-
!done:
    rts
}

mainAdvanceWindow:
.if (movingWindow && !bitmapGapLayout) { EmitAdvanceWindow() }

.macro EmitPackedColorsDecoder() {
@decompressColors:
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
}

.if (!bitmapGapLayout) { EmitPackedColorsDecoder() }

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

.macro SetAlignedLookupDestination(lowStore, highStore, offset, lowPage, highPage) {
    lda offset,x
    sta lowStore+1
    sta highStore+1
    lda lowPage,x
    sta lowStore+2
    lda highPage,x
    sta highStore+2
}

.macro EmitPrepareLookup() {
@prepareLookup:
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
    sta !packedByte+ + 1
    lda packedRowsHi,x
    adc packedOffset+1
    sta !packedByte+ + 2

    .if (movingWindow) {
        txa
        clc
        adc preparedWindowStart
        tax
    }
    lda sourceParity
    bne !odd+
    .if (fieldsPerAdvance == 2) {
        SetAlignedLookupDestination(storeEvenLow, storeEvenHigh, lowEvenLo, lowEvenHi, highEvenHi)
        SetAlignedLookupDestination(storeOddLow, storeOddHigh, lowOddLo, lowOddHi, highOddHi)
    } else {
        SetLookupDestinations(storeOddLow, storeEvenLow, lowEvenLo, lowEvenHi, lowOddLo, lowOddHi)
        SetLookupDestinations(storeOddHigh, storeEvenHigh, highEvenLo, highEvenHi, highOddLo, highOddHi)
    }
    jmp !decode+
!odd:
    // The leading high nibble is logical column zero. Low nibbles begin
    // at column one in the next packed byte, where Y is already one.
    .if (fieldsPerAdvance == 2) {
        SetAlignedLookupDestination(storeEvenLow, storeEvenHigh, lowShiftLo, lowShiftHi, highShiftHi)
        SetAlignedLookupDestination(storeOddLow, storeOddHigh, lowEvenLo, lowEvenHi, highEvenHi)
    } else {
        SetLookupDestinations(storeOddLow, storeEvenLow, lowShiftLo, lowShiftHi, lowEvenLo, lowEvenHi)
        SetLookupDestinations(storeOddHigh, storeEvenHigh, highShiftLo, highShiftHi, highEvenLo, highEvenHi)
    }
    // Below, storeEven* receives the source low nibble and storeOdd* the
    // high nibble, independent of the destination parity.
!decode:
    // Reversing the loop saves a compare per byte. The extra write from
    // the leading source nibble at odd offsets then overwrites the even
    // half's last entry, so that entry must be padding.
    ldy #(reverseLookupDecode ? lookupHalf - 1 : 0)
    .if (reverseLookupDecode && fieldsPerAdvance == 2) {
        // An even starting column already ends on a complete packed byte.
        lda sourceParity
        bne !packedByte+
        dey
    }
!packedByte:
    lax $ffff,y
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
    .if (reverseLookupDecode) {
        dey
        bpl !packedByte-
    } else {
        iny
        cpy #lookupHalf
        bne !packedByte-
    }

    inc lookupRow
    lda lookupRow
    cmp #activeRowCount
    beq !done+
    jmp !loadRow-
!done:
    rts
}

.if (!bitmapGapLayout) { EmitPrepareLookup() }

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
        @verticalFirstA:
        ldy #firstRasterA
        jmp armRaster
    }
!phaseB:
    .if (phaseBGroups.size() == 0) {
        jmp armVblank
    } else {
        lda #<(separateKernelB ? irqStableB : irqStableA)
        ldx #>(separateKernelB ? irqStableB : irqStableA)
        @verticalFirstB:
        ldy #firstRasterB
    }
armRaster:
    sta stableLow+1
    stx stableHigh+1
    sty $d012
verticalArmRaster:
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
        bcs !idleA+
        lda rasterPlansA,x
        jmp !work+
    !phaseB:
        lda lookupReady
        beq !idleB+
        cpx #rasterMapFieldsB
        bcs !idleB+
        lda rasterPlansB,x
    !work:
        inc rasterJobActive
        jmp !set+
    !idleA:
        lda #<(rasterPlanTable + rasterIdlePlanA * rasterTableStride)
        jmp !set+
    !idleB:
        lda #<(rasterPlanTable + rasterIdlePlanB * rasterTableStride)
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

.const rasterIdleChunkStride = 10
rasterIdleChunkBase:
    .if (rasterPacked) {
        .for (var i = 0; i < rasterIdleDelays.size(); i++) {
            .var end = * + rasterIdleChunkStride
            WaitCycles(rasterIdleDelays.get(i) - rasterChunkEntryCycles - rasterChunkExitCycles)
            rts
            .errorif * > end, "Raster idle routine exceeds its slot"
            // Keep table addresses independent of the wait routine's encoding.
            .fill end - *, $ea
        }
    }

armVblank:
    lda #<irqVblank
    sta $fffe
    lda #>irqVblank
    sta $ffff
    lda #<vblankRaster
    sta $d012
verticalArmVblank:
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
        RasterKernel(phaseAGroups, phaseASplits)
    }

.if (separateKernelB) {
    .align $100
}
irqStableB:
    .if (separateKernelB) {
        RasterKernel(phaseBGroups, phaseBSplits)
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
displayWindowStart:
    .if (movingWindow) { .byte 0 }
previousBWindowStart:
    .if (activeWindowWrites) { .byte 0 }
preparedWindowStart:
    .if (movingWindow) { .byte 0 }
    .if (useVerticalSine) {
        @verticalSineIndex: .byte 0
        @preparedVerticalScroll: .byte 3
    } else .if (movingWindow) {
        @windowPairsLeft: .byte windowPairsToHold
        @windowStep: .byte 1
    }
rasterMapCursor:
    .if (rasterPacked) { .byte 0 }
lookupReady:
    .if (rasterPacked) { .byte 0 }
rasterJobActive:
    .if (rasterPacked) { .byte 0 }

rasterPlansA:
    .if (rasterPacked) {
        .fill rasterMapFieldsA, <(rasterPlanTable + (rasterIdleFields + i) * rasterTableStride)
    }
rasterPlansB:
    .if (rasterPacked) {
        .fill rasterMapFieldsB, <(rasterPlanTable + (rasterIdleFields + rasterMapFieldsA + i) * rasterTableStride)
    }

.if (rasterPacked && !rasterPlanInTail) {
    .align $100
}
rasterPlanCodeTable:
    .if (rasterPacked && !rasterPlanInTail) {
        EmitRasterPlanTables()
        .errorif * - rasterPlanTable != rasterPlanBytes, "Wrong raster work plan size"
    }

.macro EmitLookupRowTables() {
    @packedRowsLo: .fill activeRowCount, <(colorData + i * packedRowBytes)
    @packedRowsHi: .fill activeRowCount, >(colorData + i * packedRowBytes)
    @lowEvenLo:    .fill rowCount, <(waveLutLow + i * lookupStride)
    @lowEvenHi:    .fill rowCount, >(waveLutLow + i * lookupStride)
    @lowOddLo:     .fill rowCount, <(waveLutLow + i * lookupStride + lookupHalf)
    @lowOddHi:     .fill rowCount, >(waveLutLow + i * lookupStride + lookupHalf)
    @lowShiftLo:   .fill rowCount, <(waveLutLow + i * lookupStride + lookupHalf - 1)
    @lowShiftHi:   .fill rowCount, >(waveLutLow + i * lookupStride + lookupHalf - 1)
    @highEvenLo:   .fill rowCount, <(waveLutHigh + i * lookupStride)
    @highEvenHi:   .fill rowCount, >(waveLutHigh + i * lookupStride)
    @highOddLo:    .fill rowCount, <(waveLutHigh + i * lookupStride + lookupHalf)
    @highOddHi:    .fill rowCount, >(waveLutHigh + i * lookupStride + lookupHalf)
    @highShiftLo:  .fill rowCount, <(waveLutHigh + i * lookupStride + lookupHalf - 1)
    @highShiftHi:  .fill rowCount, >(waveLutHigh + i * lookupStride + lookupHalf - 1)
    @colorChunkStartsLo: .byte <colorChunk0, <colorChunk1, <colorChunk2, <colorChunk3
    @colorChunkStartsHi: .byte >colorChunk0, >colorChunk1, >colorChunk2, >colorChunk3
    @colorChunkEndsLo:   .byte <colorChunk0End, <colorChunk1End, <colorChunk2End, <colorChunk3End
    @colorChunkEndsHi:   .byte >colorChunk0End, >colorChunk1End, >colorChunk2End, >colorChunk3End
}

.if (!bitmapGapLayout) { EmitLookupRowTables() }

// The stream is read only during startup. Pack it into the unused ranges
// after the resident code and lookup tables, without displacing VIC data.
.var colorStreamOffset = 0
.macro StoreColorChunk(limit) {
    .var count = min(limit - *, compressedColors.getSize() - colorStreamOffset)
    .fill count, compressedColors.get(colorStreamOffset + i)
    .eval colorStreamOffset += count
}

.macro EmitColorDecodeTables() {
    .align $100
    @lowShifted: .fill 256, (i & $f) << 4
    @highNibble: .fill 256, i >> 4
}

.if (!bitmapGapLayout) { EmitColorDecodeTables() }
writeScreenTopA:
    WriteScreenTopA()
    rts
.if (activeWindowWrites) {
    @screenTopFringeA:
        WriteScreenTopAFringe()
}
writeScreenTopB:
    WriteScreenTopB()
    rts
.if (activeWindowWrites) {
    @screenTopFringeB:
        WriteScreenTopBFringe()
}
writeColorB:
    .if (activeWindowWrites) { WindowBounds(previousBWindowStart, displayWindowStart) }
    WriteColorB()
    rts
.errorif * > screenTopA, "Player and color writers overlap VIC bank A"
colorChunk0:
    StoreColorChunk(screenTopA)
colorChunk0End:

* = screenTopA "Screen A top"
matrixTopData:
    .if (activeWindowWrites) { StoreColorChunk(screenTopA + $400) }
matrixTopDataEnd:
    .fill screenTopA + $400 - *, 0
* = screenBottomA "Screen A bottom"
matrixBottomData:
    .if (activeWindowWrites) { StoreColorChunk(screenBottomA + $400) }
matrixBottomDataEnd:
    .fill screenBottomA + $400 - *, 0
writeScreenBottomA:
    WriteScreenBottomA()
    rts
.if (activeWindowWrites) {
    @screenBottomFringeA:
        WriteScreenBottomAFringe()
}
    .if (fieldsPerAdvance == 2) { .align $100 }
waveLutLow: .fill lookupSize, 0
.errorif * > bitmapBodyStartA, "Phase A screen writer and lookup table overlap its bitmap body"
.if (useVerticalSine) {
    // Patch only immediates. Raster jobs keep their cycle positions when
    // the first IRQ, normal badlines and split badlines move together.
    @updateVerticalPhase:
        lda preparedVerticalScroll
        cmp verticalScroll
        bne !patch+
        rts
    !patch:
        sta verticalScroll
        tax
        ora #$38
        sta verticalArmRaster+1
        .for (var i = 0; i < verticalNormal.size(); i++) {
            sta verticalNormal.get(i)
        }
        ora #$80
        sta verticalArmVblank+1
        .for (var split = 0; split < 8; split++) {
            .if (verticalLate.get(split).size() != 0) {
                txa
                clc
                adc #split
                and #7
                ora #$38
                .for (var i = 0; i < verticalLate.get(split).size(); i++) {
                    sta verticalLate.get(split).get(i)
                }
            }
        }
        txa
        clc
        adc #firstRasterA-3
        sta verticalFirstA+1
        txa
        clc
        adc #firstRasterB-3
        sta verticalFirstB+1
        sec
        sbc #(fieldsPerAdvance == 2 ? 1 : 2)
        sta verticalRearmB+1
        rts
    @verticalScroll: .byte 3
    @verticalSine:
        EmitVerticalSine()
    @verticalSineEnd:
}

lowerDataA:
    StoreColorChunk(bitmapBodyStartA)
lowerDataAEnd:

* = bitmapBodyStartA "Bitmap A"
    .fill bitmapBodyEndA - bitmapBodyStartA, imageA.get(i + bitmapPrefixBytes)
gapAdvanceWindow:
    .if (bitmapGapLayout) {
        EmitAdvanceWindow()
        EmitColorDecodeTables()
        EmitPackedColorsDecoder()
        EmitColorBCopy()
    }
.errorif * > bitmapRamA + 8000, "Player code overlaps phase A raster plan"
    .if (rasterPlanInTail) {
        * = bitmapRamA + 8000
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
.if (activeWindowWrites) {
    @screenBottomFringeB:
        WriteScreenBottomBFringe()
}
    .if (fieldsPerAdvance == 2) { .align $100 }
waveLutHigh: .fill lookupSize, 0
.errorif * > bitmapBodyStartB, "Phase B screen writer and lookup table overlap its bitmap body"
lowerDataB:
    .if (!activeWindowWrites) { StoreColorChunk(bitmapBodyStartB) }
lowerDataBEnd:

* = bitmapBodyStartB "Bitmap B"
    .fill bitmapBodyEndB - bitmapBodyStartB, imageB.get(i + bitmapPrefixBytes)
    .if (bitmapGapLayout) {
        EmitLookupRowTables()
        EmitPrepareLookup()
    }
writeColorA:
    .if (activeWindowWrites) { WindowBounds(displayWindowStart, preparedWindowStart) }
    WriteColorA()
    rts
waveLutColorB: .fill colorBLookupSize, 0
colorBIndices:
    EmitSparseColorBIndices()
.if (activeWindowWrites) {
    @writeScreenTailB:
        WriteScreenTailB()
}
.errorif * > $d000, "Color RAM writer and backup lookup overlap I/O"
tailDataB:
    .if (!activeWindowWrites) { StoreColorChunk($d000) }
tailDataBEnd:
.label colorChunk1 = activeWindowWrites ? matrixTopData : lowerDataA
.label colorChunk1End = activeWindowWrites ? matrixTopDataEnd : lowerDataAEnd
.label colorChunk2 = activeWindowWrites ? matrixBottomData : lowerDataB
.label colorChunk2End = activeWindowWrites ? matrixBottomDataEnd : lowerDataBEnd
.label colorChunk3 = activeWindowWrites ? lowerDataA : tailDataB
.label colorChunk3End = activeWindowWrites ? lowerDataAEnd : tailDataBEnd
.errorif colorStreamOffset != compressedColors.getSize(), "Compressed color rows exceed the RAM available between VIC data and player code"
