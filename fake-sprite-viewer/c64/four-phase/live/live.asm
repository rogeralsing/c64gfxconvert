.const SCREEN_A = $2800
.const SCREEN_B = $2c00
.const CHARSET = $2000
.const CHARSET_B = $3000
.const SPRITE_DATA = $3800
.const FIELD_LINE = 250

.var assets = cmdLineVars.get("assets")
.var sourceData = LoadBinary(assets + "/sources.bin")
.var spriteSourceData = LoadBinary(assets + "/sprite-sources.bin")
.var sprite = LoadBinary(assets + "/sprite.bin")
.var font = LoadBinary(assets + "/charset.bin")
.var tiles = LoadBinary(assets + "/tiles.bin")
.const FIXED_CHARS = font.getSize() / 8
.const BALL_COUNT = sourceData.getSize()
.const SPRITE_COUNT = spriteSourceData.getSize()
.const TOTAL_BALL_COUNT = BALL_COUNT + SPRITE_COUNT
.errorif SPRITE_COUNT != 8 || sprite.getSize() != 64, "Expected eight sprites sharing one bitmap"

.label drawPage = $02
.label frameReady = $03
.label framePhase = $04
.label shownPhase = $05
.label hasShown = $06
.label ballOrdinal = $07
.label pendingXHigh = $08
.label ballX = $40

BasicUpstart2(start)

start:
    sei
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    sta $d017
    sta $d01b
    sta $d01d
    sta $d020
    sta $d021
    sta frameReady
    sta framePhase
    sta shownPhase
    sta hasShown

    lda #$0b
    sta $d011
    lda #$18
    sta $d016
    lda $dd02
    ora #3
    sta $dd02
    lda $dd00
    ora #3
    sta $dd00
    lda #14
    sta $d022
    sta $d025
    lda #3
    sta $d023
    ldx #SPRITE_COUNT - 1
setSpriteColor:
    sta $d027,x
    dex
    bpl setSpriteColor
    lda #6
    sta $d026
    lda #$ff
    sta $d01c

    lda #$0e
    ldx #0
setCharColor:
    sta $d800,x
    sta $d900,x
    sta $da00,x
    sta $db00,x
    inx
    bne setCharColor

    lda #$35
    sta $01
    jsr initMotion
    jsr initCharacters
    lda #SPRITE_DATA / 64
    ldx #SPRITE_COUNT - 1
setSpritePointers:
    sta SCREEN_A + $3f8,x
    sta SCREEN_B + $3f8,x
    dex
    bpl setSpritePointers

    lda #>SCREEN_A
    sta drawPage
    lda #<borderIrq
    sta $fffe
    lda #>borderIrq
    sta $ffff
    lda #<ignoreNmi
    sta $fffa
    lda #>ignoreNmi
    sta $fffb
    lda #FIELD_LINE
    sta $d012
    lda #1
    sta $d019
    sta $d01a
    cli

renderFrame:
    lda #0
    sta ballOrdinal
    lda drawPage
    ldx #>CHARSET
    cmp #>SCREEN_A
    beq beginFrame
    ldx #>CHARSET_B
beginFrame:
    jsr beginCharacterFrame
    ldx #0

renderBall:
    jsr locateBall
    jsr drawCharacterBall
    ldx ballOrdinal
    inx
    stx ballOrdinal
    cpx #BALL_COUNT
    bne renderBall

    lda #0
    sta pendingXHigh
    // Increasing source order continues the char sequence. Lower VIC slots stay in front.
    .for (var slot = SPRITE_COUNT - 1; slot >= 0; slot--) {
        ldx #TOTAL_BALL_COUNT - 1 - slot
        jsr locateBall
        clc
        adc #12
        asl
        sta pendingX + slot
        rol pendingXHigh
        tya
        clc
        adc #50
        sta pendingY + slot
    }

drawComplete:
    lda #1
    sta frameReady
waitForCommit:
    lda frameReady
    bne waitForCommit
    inc framePhase
    jsr advanceMotion
    jmp renderFrame

borderIrq:
    pha
    txa
    pha
    lda #1
    sta $d019
    lda frameReady
    bne commitFrame
    jmp fieldComplete
commitFrame:
    lda drawPage
    cmp #>SCREEN_A
    bne showB
    lda #$a8
    ldx #>SCREEN_B
    jmp showPage
showB:
    lda #$bc
    ldx #>SCREEN_A
showPage:
    sta $d018
    stx drawPage
    lda #$1b
    sta $d011
    .for (var slot = 0; slot < SPRITE_COUNT; slot++) {
        lda pendingX + slot
        sta $d000 + 2 * slot
        lda pendingY + slot
        sta $d001 + 2 * slot
    }
    lda pendingXHigh
    sta $d010
    lda #$ff
    sta $d015
    lda framePhase
    sta shownPhase
    lda #1
    sta hasShown
    lda #0
    sta frameReady
fieldComplete:
    pla
    tax
    pla
ignoreNmi:
    rti

pendingX: .fill SPRITE_COUNT, 0
pendingY: .fill SPRITE_COUNT, 0

#import "motion.asm"
#import "characters.asm"

.errorif * > CHARSET, "Live player overlaps the charset"

* = CHARSET "Fixed charset A"
    .fill font.getSize(), font.get(i) & $ff
.errorif * > SCREEN_A, "Charset overlaps the screen"

* = CHARSET_B "Fixed charset B"
    .fill font.getSize(), font.get(i) & $ff
.errorif font.getSize() >= $800, "Charset leaves no scratch glyphs"

* = SPRITE_DATA "Shared ball sprite"
    .fill sprite.getSize(), sprite.get(i) & $ff

* = $4000 "Static glyph merge routines"
    :emitCharacterBlendRoutines()
.errorif * > LIVE_CHAR_ERASE_CODE, "Live merge routines overlap erase code"

* = LIVE_CHAR_ERASE_CODE "Static tile erase routines"
    :emitCharacterEraseRoutines()
.errorif * > LIVE_CHAR_POSITION_DATA, "Live erase routines overlap position tables"

* = LIVE_CHAR_POSITION_DATA "Static character position tables"
    :emitCharacterPositionTables()
.errorif * > $a000, "Live player exceeds its code area"
