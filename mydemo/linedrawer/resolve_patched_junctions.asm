*=$e700 "Writable masks for per-cell patches"
.import binary "build/revlo.bin"
.import binary "build/revhi.bin"
.function expandNibble(n) {
    .return ((n&1)*192) | ((n&2)*24) | ((n&4)*3) | ((n&8) != 0 ? 3 : 0)
}

expandedLow: .fill 256, expandNibble(i&15)
expandedHigh: .fill 256, expandNibble(i>>4)

.var flushAddressA = List()
.var flushAddressB = List()
.macro WriteAllocated(bank, tab) {
    .for (var code = 255; code >= 201; code--) {
        .eval tab.add(*)
        ldx exactMaskLo+code
        lda expandedLow,x
        sta bank+8*code
        sta bank+8*code+1
        lda expandedHigh,x
        sta bank+8*code+2
        sta bank+8*code+3
        ldx exactMaskHi+code
        lda expandedLow,x
        sta bank+8*code+4
        sta bank+8*code+5
        lda expandedHigh,x
        sta bank+8*code+6
        sta bank+8*code+7
    }
    .eval tab.add(*)
    rts
}
WriteAllocated(CHARSET,flushAddressA)
WriteAllocated(CHARSET_B,flushAddressB)
flushEntryLo:
.for (var i=0;i<56;i++) { .byte <flushAddressA.get(55-i) }
.for (var i=0;i<56;i++) { .byte <flushAddressB.get(55-i) }
flushEntryHi:
.for (var i=0;i<56;i++) { .byte >flushAddressA.get(55-i) }
.for (var i=0;i<56;i++) { .byte >flushAddressB.get(55-i) }
flushPatchedJunctions:
    lda nextPatch
    sec
    sbc #201
    sta JCOUNT
    ldx backPair
    beq !first+
    clc
    adc #56
!first:
    tax
    lda flushEntryLo,x
    sta cwLayout
    lda flushEntryHi,x
    sta cwLayout+1
    jmp (cwLayout)
.assert "Flush ends below interrupt vectors", * <= $fffa,true
