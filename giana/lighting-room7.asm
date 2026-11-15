// Phase-major colors and a cell-address map keep the second room's light
// effect small. The call follows the last picture line at raster 250.
.const ROOM7_LIGHT_DESTINATION = $fb

applyRoom7Light:
    ldx lightLevel
    lda room7LightScreenLow,x
    sta room7LightScreenRead + 1
    lda room7LightScreenHigh,x
    sta room7LightScreenRead + 2
    lda room7LightColorLow,x
    sta room7LightColorRead + 1
    lda room7LightColorHigh,x
    sta room7LightColorRead + 2
    ldx #0
    ldy #0
!cell:
    lda scene7LightCellLow,x
    sta ROOM7_LIGHT_DESTINATION
    lda scene7LightCellHigh,x
    sta ROOM7_LIGHT_DESTINATION + 1
room7LightScreenRead:
    lda scene7LightScreen0,x
    sta (ROOM7_LIGHT_DESTINATION),y
    // Color RAM and screen RAM share the cell's low address byte.
    lda ROOM7_LIGHT_DESTINATION + 1
    clc
    adc #$d4
    sta ROOM7_LIGHT_DESTINATION + 1
room7LightColorRead:
    lda scene7LightColor0,x
    sta (ROOM7_LIGHT_DESTINATION),y
    inx
    cpx #SCENE7_LIGHT_TILE_COUNT
    bne !cell-
    rts

room7LightScreenLow: .byte <scene7LightScreen0, <scene7LightScreen1, <scene7LightScreen2
room7LightScreenHigh: .byte >scene7LightScreen0, >scene7LightScreen1, >scene7LightScreen2
room7LightColorLow: .byte <scene7LightColor0, <scene7LightColor1, <scene7LightColor2
room7LightColorHigh: .byte >scene7LightColor0, >scene7LightColor1, >scene7LightColor2
codeEnd:
