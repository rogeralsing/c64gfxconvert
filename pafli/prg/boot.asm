// Reuse the validated AFLI startup, backwards phase-B relocation, and timing shim.
#import "../../afli-viewer/prg/boot.asm"

.const frameCounter = $02f0

* = $20a0 "PAFLI frame postlude"
afterVisibleImage:
    // Close the lower border before switching the next frame's four-pixel phase.
    lda #$30
    sta $d011
    lda $d016
    eor #4
    sta $d016
    inc frameCounter
    jmp $0f02  // Original PAL engine flips the VIC bank and re-arms the IRQ.

* = $20c0 "PAFLI standalone entry"
pafliStart:
    lda #0
    sta frameCounter
    jmp start
