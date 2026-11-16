// Complete bitmap bytes preserve surrounding original art at both patch steps.
introBlockData:
.const INTRO_BUMP_PATCH_COUNT = 10
introBumpAddressLow:
    .byte $d2,$da,$d3,$d4,$d5,$d6,$d7,$df,$10,$18
introBumpAddressHigh:
    .byte $25,$25,$25,$25,$25,$25,$25,$25,$27,$27
introBumpValues:
    .byte $aa,$85,$ae,$af,$bf,$aa,$00,$0a,$55,$50
.const INTRO_SPENT_PATCH_COUNT = 14
introSpentAddressLow:
    .byte $d2,$da,$cb,$d3,$cc,$d4,$cd,$d5,$ce,$d6,$cf,$10,$18,$09
introSpentAddressHigh:
    .byte $25,$25,$25,$25,$25,$25,$25,$25,$25,$25,$25,$27,$27,$27
introSpentValues:
    .byte $55,$55,$55,$00,$20,$00,$a0,$00,$00,$00,$20,$00,$00,$00
introBlockDataEnd:
.assert "Intro block patches fit one free page", introBlockDataEnd - introBlockData <= $100, true
