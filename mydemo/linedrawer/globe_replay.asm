// Exact replay for selected lines after clipping. An unmatched line enters
// the usual drawer with its original endpoint and buffer parameters.
.import source "study_replay_block.asm"

.label globeReplayDeltaX = ldxa
.label globeReplayDeltaY = ldya
.label globeReplayLocalY = lmx
.label globeReplayRebase = lmy

*=$c600 "Globe line replay dispatch"
globeReplayLine:
    .if (GLOBE_REPLAY_STATS) {
        inc globeReplayAttempts
        bne !counted+
        inc globeReplayAttempts+1
    !counted:
    }
    lda lx1
    sec
    sbc lx0
    tax
    lda ly1
    sec
    sbc ly0
    sta globeReplayDeltaY
    clc
    adc globeReplayDisplacement,x
    tay
    txa
    cmp globeReplayTagX,y
    bne globeReplayMiss
    lda globeReplayDeltaY
    cmp globeReplayTagY,y
    bne globeReplayMiss
    stx globeReplayDeltaX
    ldx globeReplayHead,y
    cpx #$ff
    bne !local+
globeReplayMiss:
    jmp drawCharLine
!local:
    lda ly0
    and #3
    asl
    asl
    sta globeReplayLocalY
    lda lx0
    and #3
    ora globeReplayLocalY
    tay
!check:
    tya
    cmp globeReplayLocal,x
    beq !keyMatch+
    lda globeReplayNext,x
    tax
    cpx #$ff
    bne !check-
    jmp globeReplayMiss
!keyMatch:
    // The viewport is wider than 127 pixels. Keep dx outside the signed
    // byte range from matching an otherwise identical wrapped key.
    ldy lx1
    cpy lx0
    lda globeReplayDeltaX
    bmi !left+
    bcc globeReplayMiss
    bcs globeReplayHit
!left:
    bcs globeReplayMiss
globeReplayHit:
    .if (GLOBE_REPLAY_STATS) {
        inc globeReplayHits
        bne !counted+
        inc globeReplayHits+1
    !counted:
    }
    lda globeReplayCodeLo,x
    sta globeReplayRun+1
    lda globeReplayCodeHi,x
    sta globeReplayRun+2
    lda globeReplayBaseDelta,x
    sta globeReplayRebase

    lda ly0
    lsr
    lsr
    tax
    lda lx0
    lsr
    lsr
    clc
    adc charRowLo,x
    sta scrLo
    lda charRowHi,x
    adc baseHi
    sta scrHi
    lda scrLo
    clc
    adc baseLo
    sta scrLo
    bcc !screenReady+
    inc scrHi
!screenReady:
    // The lowest literal offset may precede the first stamp.
    lda globeReplayRebase
    beq globeReplayRun
    clc
    adc scrLo
    sta scrLo
    bcs globeReplayRun
    dec scrHi
globeReplayRun:
    jmp $ffff

studyReplayCompactStamp:
    StudyReplayCompactHandler()
studyReplayCollision:
    sta jcode
studyReplayJoin:
    StudyReplayCollisionHandler()

globeReplayAttempts:     .word 0
globeReplayHits:         .word 0
globeReplayStatsEnabled: .byte GLOBE_REPLAY_STATS ? 1 : 0
.assert "Globe replay dispatch fits before the key tables", * <= $c700, true

// Build-time template input. Only the keys and native instructions below
// are shipped in the PRG. A slot can share another slot's literal kernel.
.var replayFixture = LoadBinary("build/globe-replay-data.bin")
.var replayKeyCount = replayFixture.get(0) & $ff
.var replayKeyStart = 1025
.var replayKernelCountOffset = replayKeyStart + 4 * replayKeyCount
.var replayKernelCount = replayFixture.get(replayKernelCountOffset) & $ff
.var replayRecord = replayKernelCountOffset + 1
.var replayEntryPoints = List()

*=$e000 "Generated globe line replay kernels"
.for (var kernel = 0; kernel < replayKernelCount; kernel++) {
    .eval replayEntryPoints.add(*)
    .var stampCount = replayFixture.get(replayRecord) & $ff
    .var offsets = List()
    .var codes = List()
    .eval replayRecord++
    .for (var stamp = 0; stamp < stampCount; stamp++) {
        .eval offsets.add(replayFixture.get(replayRecord) & $ff)
        .eval codes.add(replayFixture.get(replayRecord + 1) & $ff)
        .eval replayRecord += 2
    }
    StudyReplayCompactBlock(offsets, codes)
    rts
}
.assert "Replay kernels fit below interrupt vectors", * <= $fffa, true
.assert "Replay records consume the generated payload", replayRecord == replayFixture.getSize(), true

*=$c700 "Globe line replay keys"
globeReplayDisplacement: .fill 256, replayFixture.get(1 + i)
globeReplayTagX: .fill 256, replayFixture.get(257 + i)
globeReplayTagY: .fill 256, replayFixture.get(513 + i)
globeReplayHead: .fill 256, replayFixture.get(769 + i)
globeReplayLocal: .fill replayKeyCount, replayFixture.get(replayKeyStart + i)
globeReplayNext: .fill replayKeyCount, replayFixture.get(replayKeyStart + replayKeyCount + i)
globeReplayBaseDelta: .fill replayKeyCount, replayFixture.get(replayKeyStart + replayKeyCount * 2 + i)
globeReplayCodeLo: .fill replayKeyCount, <replayEntryPoints.get(replayFixture.get(replayKeyStart + replayKeyCount * 3 + i) & $ff)
globeReplayCodeHi: .fill replayKeyCount, >replayEntryPoints.get(replayFixture.get(replayKeyStart + replayKeyCount * 3 + i) & $ff)
.assert "Globe line replay keys fit below I/O", * <= $d000, true
