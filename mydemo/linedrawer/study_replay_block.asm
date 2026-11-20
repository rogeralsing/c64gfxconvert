// Generate one literal stamp per occupied cell of a motif. The caller
// rebases the offsets to an unsigned byte span from scrLo/scrHi, supplies
// line-bank glyph codes, and ends the generated routine with RTS.

.macro StudyReplayStamp(offset, glyph) {
    ldy #offset
    lda (scrLo),y
    beq !blank+
    cmp #glyph
    beq !done+
    lda #glyph
    jsr studyReplayCollision
    jmp !done+
!blank:
    lda #glyph
    sta (scrLo),y
!done:
}

.macro StudyReplayBlock(offsets, glyphs) {
    .assert "One offset per replay glyph", offsets.size() == glyphs.size(), true
    .for (var stamp = 0; stamp < glyphs.size(); stamp++) {
        StudyReplayStamp(offsets.get(stamp), glyphs.get(stamp))
    }
}

// Emit at studyReplayJoin once in the fixture, with incoming code in jcode.
// The merge uses the same pointer and joint-bank state as the normal walker.
.macro StudyReplayCollisionHandler() {
    tya
    clc
    adc scrLo
    sta jptrLo
    lda scrHi
    adc #0
    sta jptrHi
    jmp stampJoint
}

.macro StudyReplayCompactBlock(offsets, glyphs) {
    .assert "One offset per replay glyph", offsets.size() == glyphs.size(), true
    .for (var stamp = 0; stamp < glyphs.size(); stamp++) {
        ldy #offsets.get(stamp)
        ldx #glyphs.get(stamp)
        jsr studyReplayCompactStamp
    }
}

.macro StudyReplayCompactHandler() {
    lda (scrLo),y
    beq !blank+
    stx jcode
    cmp jcode
    beq !done+
    jmp studyReplayJoin
!blank:
    txa
    sta (scrLo),y
!done:
    rts
}
