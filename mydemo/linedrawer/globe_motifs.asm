// Decode only the next eight aligned samples. The seven moves between
// them choose literal stamps. The eighth move changes the next phase and
// address, independently of the chosen kernel.
.label globeMotifsFrac8 = ldxa
.label globeMotifsWhole8 = ldya
.label globeMotifsScreen = lmx
.label globeMotifsOrient4 = entLo
.label globeMotifsOrient32 = entHi
.label globeMotifsSplitKey = glyLo

.macro GlobeMotifsAddress(codeLo, codeHi, backstep, entry, origin) {
    lda codeLo,x
    sta entry+1
    lda codeHi,x
    sta entry+2
    lda origin
    sec
    sbc backstep,x
    sta globeMotifsScreen
    lda origin+1
    sbc #0
    sta globeMotifsScreen+1
}

.macro GlobeMotifsStamp(offset, code, last) {
    ldy #offset
    ldx #code
    .if (last) {
        jmp globeMotifsCheckedStamp
    } else {
        jsr globeMotifsCheckedStamp
    }
}

*=$c600 "Globe short motif walker"
globeMotifsBegin:
    lda cwOrient
    asl
    asl
    sta globeMotifsOrient4
    asl
    asl
    asl
    sta globeMotifsOrient32
    lda cwRemain
    cmp #8
    bcc globeMotifsFinish
    lda cwAdvanceLo+3
    asl
    sta globeMotifsFrac8
    lda cwAdvanceHi+3
    rol
    sta globeMotifsWhole8
    lda cwOrient
    clc
    adc #>globeMotifsSelectors
    sta globeMotifsLookup+2
globeMotifsLoop:
    lda cwRemain
    cmp #8
    bcs globeMotifsToken
globeMotifsFinish:
    cmp #4
    bcc !tail+
    jsr globeMotifsOne
    lda cwRemain
    sec
    sbc #4
    sta cwRemain
    beq !done+
    AdvanceWalkBlock(true)
!tail:
    jmp charWalkPartial
!done:
    rts

globeMotifsRun:
    jmp $ffff
globeMotifsOneRun:
    jmp $ffff

// Sorted phase thresholds classify the next seven decisions in three
// comparisons. A true Q8 rate of 256 has eight whole moves and no fraction.
globeMotifsToken:
    lda cwAdvanceHi+3
    cmp #4
    bne !fractional+
    lda #212                   // (54 - 1) * 4, seven minor moves
    jmp globeMotifsFoundToken
!fractional:
    ldx cwSlope
    lda cwPhase
    cmp globeMotifsThreshold3,x
    bcc !below4+
    cmp globeMotifsThreshold5,x
    bcc !below6+
    cmp globeMotifsThreshold6,x
    bcc !token6+
    lda globeMotifsToken7,x
    jmp globeMotifsFoundToken
!token6:
    lda globeMotifsToken6,x
    jmp globeMotifsFoundToken
!below6:
    cmp globeMotifsThreshold4,x
    bcc !token4+
    lda globeMotifsToken5,x
    jmp globeMotifsFoundToken
!token4:
    lda globeMotifsToken4,x
    jmp globeMotifsFoundToken
!below4:
    cmp globeMotifsThreshold1,x
    bcc !below2+
    cmp globeMotifsThreshold2,x
    bcc !token2+
    lda globeMotifsToken3,x
    jmp globeMotifsFoundToken
!token2:
    lda globeMotifsToken2,x
    jmp globeMotifsFoundToken
!below2:
    cmp globeMotifsThreshold0,x
    bcc !token0+
    lda globeMotifsToken1,x
    jmp globeMotifsFoundToken
!token0:
    lda globeMotifsToken0,x
globeMotifsFoundToken:
    ora cwMinorLocal
    tay
globeMotifsLookup:
    ldx $ff00,y
    cpx #$ff
    beq !split+
    GlobeMotifsAddress(globeMotifsPairLo, globeMotifsPairHi, globeMotifsPairBack, globeMotifsRun, scrLo)
    jsr globeMotifsRun
    jmp globeMotifsPairDone
!split:
    // The same token supplies both single kernels and the second
    // group's screen offset. Keep the original walk state until both draw.
    sty globeMotifsSplitKey
    lda globeMotifsFirstKey,y
    ora globeMotifsOrient32
    tax
    jsr globeMotifsSingleAtCurrent
    ldy globeMotifsSplitKey
    lda globeMotifsSecondKey,y
    cmp #$80
    and #$1f
    ora globeMotifsOrient32
    tax
    lda cwOrient
    rol
    tay
    lda scrLo
    clc
    adc globeMotifsSecondLo,y
    sta globeMotifsScreen
    lda scrHi
    adc globeMotifsSecondHi,y
    sta globeMotifsScreen+1
    GlobeMotifsAddress(globeMotifsSingleLo, globeMotifsSingleHi, globeMotifsSingleBack, globeMotifsOneRun, globeMotifsScreen)
    jsr globeMotifsOneRun
globeMotifsPairDone:
    lda cwRemain
    sec
    sbc #8
    sta cwRemain
    beq !done+
    lda cwPhase
    clc
    adc globeMotifsFrac8
    sta cwPhase
    lda cwMinorLocal
    adc globeMotifsWhole8
    tax
    and #3
    sta cwMinorLocal
    txa
    lsr
    lsr
    ora globeMotifsOrient4
    tax
    lda scrLo
    clc
    adc globeMotifsAdvanceLo,x
    sta scrLo
    lda scrHi
    adc globeMotifsAdvanceHi,x
    sta scrHi
    jmp globeMotifsLoop
!done:
    rts

// Choose a literal kernel for the lone full group at the end of a line.
globeMotifsOne:
    lda cwPhase
    cmp cwThreshold+1
    bcc !below+
    ldx #2
    cmp cwThreshold+2
    bcc !shape+
    inx
    bcs !shape+
!below:
    ldx #0
    cmp cwThreshold
    bcc !shape+
    inx
!shape:
    ldy cwShapes,x
    lda cwMinorLocal
    asl
    asl
    asl
    ora globeMotifsThreeMoves,y
    ora globeMotifsOrient32
    tax
globeMotifsSingleAtCurrent:
    GlobeMotifsAddress(globeMotifsSingleLo, globeMotifsSingleHi, globeMotifsSingleBack, globeMotifsOneRun, scrLo)
    jmp globeMotifsOneRun

globeMotifsCheckedStamp:
    lda (globeMotifsScreen),y
    beq !blank+
    stx jcode
    cmp jcode
    beq !done+
    tya
    clc
    adc globeMotifsScreen
    sta jptrLo
    lda globeMotifsScreen+1
    adc #0
    sta jptrHi
    jmp stampJoint
!blank:
    txa
    sta (globeMotifsScreen),y
!done:
    rts
.assert "Motif walker fits before selectors", * <= $c800, true

// The build-time payload supplies literal character codes and cell offsets.
// The object contains only the compiled kernels and their native lookup tables.
.var globeMotifsAsset = LoadBinary("build/globe-motifs-data.bin")
.var globeMotifsPairCount = globeMotifsAsset.get(0) & $ff
.var globeMotifsRecord = 1 + (15 + 8) * 256
.var globeMotifsEntries = List()
.var globeMotifsRebases = List()

*=$e000 "Generated globe motif kernels"
.for (var kernel = 0; kernel < globeMotifsPairCount + 256; kernel++) {
    .eval globeMotifsEntries.add(*)
    .eval globeMotifsRebases.add((-globeMotifsAsset.get(globeMotifsRecord)) & $ff)
    .var stampCount = globeMotifsAsset.get(globeMotifsRecord + 1) & $ff
    .eval globeMotifsRecord += 2
    .for (var stamp = 0; stamp < stampCount; stamp++) {
        GlobeMotifsStamp(globeMotifsAsset.get(globeMotifsRecord) & $ff, globeMotifsAsset.get(globeMotifsRecord + 1) & $ff, stamp == stampCount - 1)
        .eval globeMotifsRecord += 2
    }
}
.assert "Motif kernels fit below interrupt vectors", * <= $fffa, true
.assert "Motif records precede two split lookup pages", globeMotifsRecord + 512 == globeMotifsAsset.getSize(), true

*=$1a00 "Motif phase thresholds 0–5"
globeMotifsThreshold0: .fill 256, globeMotifsAsset.get(1 + i)
globeMotifsThreshold1: .fill 256, globeMotifsAsset.get(257 + i)
globeMotifsThreshold2: .fill 256, globeMotifsAsset.get(513 + i)
globeMotifsThreshold3: .fill 256, globeMotifsAsset.get(769 + i)
globeMotifsThreshold4: .fill 256, globeMotifsAsset.get(1025 + i)
globeMotifsThreshold5: .fill 256, globeMotifsAsset.get(1281 + i)

*=$3a00 "Motif threshold 6 and phase tokens 0–4"
globeMotifsThreshold6: .fill 256, globeMotifsAsset.get(1537 + i)
globeMotifsToken0: .fill 256, globeMotifsAsset.get(1793 + i)
globeMotifsToken1: .fill 256, globeMotifsAsset.get(2049 + i)
globeMotifsToken2: .fill 256, globeMotifsAsset.get(2305 + i)
globeMotifsToken3: .fill 256, globeMotifsAsset.get(2561 + i)
globeMotifsToken4: .fill 256, globeMotifsAsset.get(2817 + i)

*=$7700 "Motif phase tokens 5–7"
globeMotifsToken5: .fill 256, globeMotifsAsset.get(3073 + i)
globeMotifsToken6: .fill 256, globeMotifsAsset.get(3329 + i)
globeMotifsToken7: .fill 256, globeMotifsAsset.get(3585 + i)
.function GlobeMotifsMoves(shape) {
    .var a = shape & 3
    .var b = (shape >> 2) & 3
    .var c = (shape >> 4) & 3
    .return (a | ((b - a) << 1) | ((c - b) << 2)) & $ff
}
globeMotifsThreeMoves: .fill 64, GlobeMotifsMoves(i)

.function GlobeMotifsScreenStep(orient, majorCells, minorCells) {
    .var x = (orient & 1) == 0 ? 1 : -1
    .var y = (orient & 2) == 0 ? 40 : -40
    .return (orient & 4) == 0 ? majorCells * x + minorCells * y : majorCells * y + minorCells * x
}
globeMotifsAdvanceLo: .fill 32, <GlobeMotifsScreenStep(i >> 2, 2, i & 3)
globeMotifsAdvanceHi: .fill 32, >GlobeMotifsScreenStep(i >> 2, 2, i & 3)
globeMotifsSecondLo: .fill 16, <GlobeMotifsScreenStep(i >> 1, 1, i & 1)
globeMotifsSecondHi: .fill 16, >GlobeMotifsScreenStep(i >> 1, 1, i & 1)
.assert "Motif advance tables fit before split keys", * <= $7b00, true

*=$7b00 "First single motif key"
globeMotifsFirstKey: .fill 256, globeMotifsAsset.get(globeMotifsRecord + i)

*=$1000 "Single motif entry addresses"
globeMotifsSingleLo: .fill 256, <globeMotifsEntries.get(globeMotifsPairCount + i)
globeMotifsSingleHi: .fill 256, >globeMotifsEntries.get(globeMotifsPairCount + i)
*=$b200 "Single motif origins"
globeMotifsSingleBack: .fill 256, globeMotifsRebases.get(globeMotifsPairCount + i)

*=$9e00 "Pair motif entry and origin tables"
globeMotifsPairLo: .fill globeMotifsPairCount, <globeMotifsEntries.get(i)
globeMotifsPairHi: .fill globeMotifsPairCount, >globeMotifsEntries.get(i)
globeMotifsPairBack: .fill globeMotifsPairCount, globeMotifsRebases.get(i)
.assert "Pair entry tables fit before split keys", * <= $a100, true

*=$a100 "Second single motif key"
globeMotifsSecondKey: .fill 256, globeMotifsAsset.get(globeMotifsRecord + 256 + i)

*=$c800 "Pair motif selectors by octant"
globeMotifsSelectors: .fill 8 * 256, globeMotifsAsset.get(3841 + i)
