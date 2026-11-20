// Select one complete character period after the stock partial head.
// For supported slopes the fractional phase and local minor position
// return to their original values after each period.
.label globeRepeatStepLo = ldxa
.label globeRepeatStepHi = ldya
.label globeRepeatBackstep = lmx
.label globeRepeatPeriodsLeft = lmy

.macro GlobeRepeatStamp(offset, code, last) {
    ldy #offset
    ldx #code
    .if (last) {
        jmp globeRepeatCheckedStamp
    } else {
        jsr globeRepeatCheckedStamp
    }
}

*=$c600 "Globe repeated line motifs"
globeRepeatTry:
    // The char-walk entry already checked for a zero 4-sample fraction.
    ldx cwAdvanceHi+3
    lda cwRemain
    cmp globeRepeatMinimum,x
    bcs globeRepeatSelect
    jmp charWalkFull

globeRepeatSelect:
    tay
    and globeRepeatResidueMask,x
    sta cwRemain
    tya
    lsr
    lsr
    ldy globeRepeatExtraShifts,x
    beq !counted+
!shift:
    lsr
    dey
    bne !shift-
!counted:
    sta globeRepeatPeriodsLeft

    lda cwPhase
    and globeRepeatPhaseMask,x
    lsr
    cpx #2
    bne !phase+
    lsr
!phase:
    clc
    adc globeRepeatPhaseBase,x
    sta globeRepeatBackstep
    lda cwOrient
    asl
    asl
    ora cwMinorLocal
    ora globeRepeatBackstep
    tay

    ldx globeRepeatKernel,y
    lda globeRepeatEntryLo,x
    sta globeRepeatRun+1
    lda globeRepeatEntryHi,x
    sta globeRepeatRun+2
    lda globeRepeatMoveLo,y
    sta globeRepeatStepLo
    lda globeRepeatMoveHi,y
    sta globeRepeatStepHi
    lda globeRepeatBack,y
    sta globeRepeatBackstep

    lda scrLo
    sec
    sbc globeRepeatBackstep
    sta scrLo
    lda scrHi
    sbc #0
    sta scrHi

globeRepeatLoop:
    jsr globeRepeatRun
    lda scrLo
    clc
    adc globeRepeatStepLo
    sta scrLo
    lda scrHi
    adc globeRepeatStepHi
    sta scrHi
    dec globeRepeatPeriodsLeft
    bne globeRepeatLoop

    lda cwRemain
    beq !done+
    // Restore the stock origin and resume using the same Q8 phase.
    lda scrLo
    clc
    adc globeRepeatBackstep
    sta scrLo
    bcc !tail+
    inc scrHi
!tail:
    lda cwRemain
    cmp #4
    bcc !partial+
    jmp charWalkFull
!partial:
    jmp charWalkPartial
!done:
    rts

globeRepeatRun:
    jmp $ffff

globeRepeatCheckedStamp:
    lda (scrLo),y
    beq !blank+
    stx jcode
    cmp jcode
    beq !done+
    tya
    clc
    adc scrLo
    sta jptrLo
    lda scrHi
    adc #0
    sta jptrHi
    jmp stampJoint
!blank:
    txa
    sta (scrLo),y
!done:
    rts

// Indices are the integer minor displacement after four major samples.
// Rates 0, 64, 128 and 256 repeat after 1, 4, 2 and 1 full groups.
// The stock path handles rate 192. Visible lines have at most 160 samples.
globeRepeatMinimum:     .byte 8, 32, 16, 255, 8
globeRepeatResidueMask: .byte 3, 15, 7, 0, 3
globeRepeatExtraShifts: .byte 0, 2, 1, 0, 0
globeRepeatPhaseMask:   .byte 0, $c0, $80, 0, 0
globeRepeatPhaseBase:   .byte 0, 32, 160, 0, 224
.assert "Repeat dispatcher fits before context pages", * <= $c800, true

.var globeRepeatAsset = LoadBinary("build/globe-repeat-data.bin")
.var globeRepeatKernelCount = globeRepeatAsset.get(0) & $ff
.var globeRepeatRecord = 1 + 4 * 256
.var globeRepeatEntries = List()

*=$e000 "Generated repeat kernels"
.for (var kernel = 0; kernel < globeRepeatKernelCount; kernel++) {
    .eval globeRepeatEntries.add(*)
    .var count = globeRepeatAsset.get(globeRepeatRecord) & $ff
    .eval globeRepeatRecord++
    .for (var stamp = 0; stamp < count; stamp++) {
        GlobeRepeatStamp(globeRepeatAsset.get(globeRepeatRecord) & $ff, globeRepeatAsset.get(globeRepeatRecord + 1) & $ff, stamp == count - 1)
        .eval globeRepeatRecord += 2
    }
}
.assert "Repeat kernels fit below interrupt vectors", * <= $fffa, true
.assert "Repeat records consume the generated asset", globeRepeatRecord == globeRepeatAsset.getSize(), true

*=$c800 "Repeat motif selection and signed address steps"
globeRepeatKernel: .fill 256, globeRepeatAsset.get(1 + i)
globeRepeatBack: .fill 256, (-globeRepeatAsset.get(257 + i)) & $ff
globeRepeatMoveLo: .fill 256, globeRepeatAsset.get(513 + i)
globeRepeatMoveHi: .fill 256, globeRepeatAsset.get(769 + i)
globeRepeatEntryLo: .fill globeRepeatKernelCount, <globeRepeatEntries.get(i)
globeRepeatEntryHi: .fill globeRepeatKernelCount, >globeRepeatEntries.get(i)
.assert "Repeat context pages fit below I/O", * <= $d000, true
