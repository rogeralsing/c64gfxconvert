// Megaplot draws one continuous moving polyline in hires character mode.
// Each node is evaluated once. Each segment receives two adjacent nodes.
.const SEGMENTS = cmdLineVars.get("segments").asNumber()
.const NODES = SEGMENTS + 1
// The X waves span 156 logical pixels. The Y waves span 96.
.const MAX_DELTA = 156
.const SHORT_DELTA = 80
.assert "Megaplot supports 4 through 48 segments", SEGMENTS >= 4 && SEGMENTS <= 48, true

.const SCREEN = $0400
.const SCREEN_B = $2c00
.const CHARSET = $2000
.const CHARSET_B = $3000
.const charFirst = $4000
.const charSecond = $5000
.const charTransform = $6000
.const charSlope = $6800

.label lx0 = $02
.label ly0 = $03
.label lx1 = $04
.label ly1 = $05
.label scrLo = $16
.label scrHi = $17
.label jcode = $39
.label patLo = $3a
.label patHi = $3b
.label hidx = $3c
.label dstLo = $3d
.label dstHi = $3e
.label jptrLo = $3f
.label jptrHi = $40
.label frameIndex = $74
.label baseHi = $76
.label drawCharsetHi = $a8
.label backPair = $a9
.label segmentIndex = $aa
.label phase2 = $ab
.label phase3 = $ac

BasicUpstart2(start)

* = $0900 "Animation and glyph composition"
start:
    sei
    cld
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #3
    sta $dd00                  // Bank 0 contains both screen/charset pairs.
    lda #$0b
    sta $d011
    lda #$18
    sta $d018
    lda #$08
    sta $d016
    lda #0
    sta $d020
    sta $d021
    sta frameIndex
    ldx #0
!clear:
    sta SCREEN,x
    sta SCREEN+$100,x
    sta SCREEN+$200,x
    sta SCREEN+$300,x
    sta SCREEN_B,x
    sta SCREEN_B+$100,x
    sta SCREEN_B+$200,x
    sta SCREEN_B+$300,x
    inx
    bne !clear-
    lda #1
    sta backPair
!white:
    sta $d800,x
    sta $d900,x
    sta $da00,x
    sta $db00,x
    inx
    bne !white-
    lda #$1b
    sta $d011

waveLoop:
    ldx backPair
    lda screenPages,x
    sta baseHi
    lda charsetPages,x
    sta drawCharsetHi
    lda #0
    sta JCOUNT
    sta jointOverflow
    cpx #0
    beq !screenA+
    jsr clearWaveB
    jmp !cleared+
!screenA:
    jsr clearWaveA
!cleared:
    lda frameIndex
    asl
    sta phase2
    clc
    adc frameIndex
    sta phase3
    ldx #SEGMENTS
!node:
    lda xPhase1,x
    clc
    adc phase2
    tay
    lda waveX1,y
    clc
    adc #79
    sta nodeX,x
    lda xPhase2,x
    sec
    sbc phase3
    tay
    lda waveX2,y
    clc
    adc nodeX,x
    sta nodeX,x

    lda yPhase1,x
    sec
    sbc phase2
    tay
    lda waveY1,y
    clc
    adc #49
    sta nodeY,x
    lda yPhase2,x
    clc
    adc phase3
    tay
    lda waveY2,y
    clc
    adc nodeY,x
    sta nodeY,x
    dex
    bpl !node-

    lda #0
    sta segmentIndex
!segment:
    ldx segmentIndex
    lda nodeX,x
    sta lx0
    lda nodeY,x
    sta ly0
    lda nodeX+1,x
    sta lx1
    lda nodeY+1,x
    sta ly1
    jsr drawCharLine
    inc segmentIndex
    lda segmentIndex
    cmp #SEGMENTS
    bne !segment-

    // Wait for the PAL border before switching screen and character set together.
!border:
    bit $d011
    bmi !show+
    lda $d012
    cmp #$30
    bcc !show+
    cmp #$fc
    bcc !border-
!show:
    ldx backPair
    lda vicPairs,x
presentFrame:
    sta $d018
    txa
    eor #1
    sta backPair
    inc frameIndex
    jmp waveLoop

screenPages:
    .byte >SCREEN, >SCREEN_B
charsetPages:
    .byte >CHARSET, >CHARSET_B
vicPairs:
    .byte $18, $bc
// Span 235 of the 256 phases so the last and first joints remain independent.
.function NodePhase(i) {
    .return floor(235*i/SEGMENTS)
}
xPhase1:
    .fill NODES, (2*NodePhase(i) + 32) & 255
xPhase2:
    .fill NODES, (5*NodePhase(i) + 11) & 255
yPhase1:
    .fill NODES, (3*NodePhase(i) + 53) & 255
yPhase2:
    .fill NODES, (4*NodePhase(i)) & 255
nodeX:
    .fill NODES, 0
nodeY:
    .fill NODES, 0

// The free-moving chain can occupy any character row.
.macro ClearWave(screen) {
    ldx #39
!column:
    .for (var row=0; row<25; row++) {
        sta screen + 40*row,x
    }
    dex
    bpl !column-
    rts
}
clearWaveA:
    ClearWave(SCREEN)
clearWaveB:
    ClearWave(SCREEN_B)

// ---- vertex-joint composition ----
// jcode = incoming screencode, (jptrLo) = cell. Existing content is ORed
// with the incoming pattern and resolved as: line-bank hash hit -> joint
// patch slot (glyph expanded into chars 201..255) -> fallback overwrite.
stampJoint:
    ldy #0
    lda (jptrLo),y
    bne sjCompose
    lda jcode                 // blank cell: plain stamp
    sta (jptrLo),y
    rts
sjCompose:
    cmp #201
    bcs sjFromSlot            // existing content is a joint slot
    tax
    lda REVLO,x
    sta patLo
    lda REVHI,x
    sta patHi
    jmp sjHave
sjFromSlot:
    sec
    sbc #201
    asl
    tay
    lda JOINTT,y
    sta patLo
    lda JOINTT+1,y
    sta patHi
sjHave:
    ldx jcode
    lda REVLO,x
    ora patLo
    sta patLo
    lda REVHI,x
    ora patHi
    sta patHi
    jsr hashLookup            // already a line glyph?
    bne sjStore
    ldx #0                    // joint slot scan (slot index)
sjScan:
    cpx JCOUNT
    beq sjAlloc
    txa
    asl
    tay
    lda patLo
    cmp JOINTT,y
    bne sjNext
    lda patHi
    cmp JOINTT+1,y
    bne sjNext
    txa
    clc
    adc #201
    jmp sjStore
sjNext:
    inx
    jmp sjScan
sjAlloc:
    lda JCOUNT
    cmp #55
    bcc sjPlace
    ldx jointOverflow
    cpx #$ff
    beq !overflow+
    inc jointOverflow
!overflow:
    lda jcode                 // budget exhausted -> overwrite
    jmp sjStore
sjPlace:
    ldx JCOUNT
    txa
    asl
    tay
    lda patLo
    sta JOINTT,y
    lda patHi
    sta JOINTT+1,y
    inc JCOUNT
    txa
    clc
    adc #201
    pha                       // slot code: patchGlyph clobbers X
    jsr patchGlyph            // slot index in X
    pla
sjStore:
    ldy #0
    sta (jptrLo),y
    rts

// The build gives each high byte a displacement with no collisions between
// known glyphs. A lookup checks exactly one slot, including for misses.
hashLookup:
    ldx patHi
    lda HASH_DISP_LO,x
    clc
    adc patLo
    sta hidx
    lda HASH_DISP_HI,x
    adc #0
    and #1
    bne !upper+
    ldx hidx
    lda HASHKL,x
    cmp patLo
    bne hlMiss
    lda HASHKH,x
    cmp patHi
    bne hlMiss
    lda HASHV,x
    rts
!upper:
    ldx hidx
    lda HASHKL+$100,x
    cmp patLo
    bne hlMiss
    lda HASHKH+$100,x
    cmp patHi
    bne hlMiss
    lda HASHV+$100,x
    rts
hlMiss:
    lda #0
    rts

// Expand (patLo,patHi) into the reserve glyph indexed by X.
patchGlyph:
    txa
    clc
    adc #201
    pha
    asl
    asl
    asl
    sta dstLo
    pla
    lsr
    lsr
    lsr
    lsr
    lsr
    clc
    adc drawCharsetHi
    sta dstHi
    ldy #0
    lda patLo
    and #$0f
    tax
    lda niblut,x
    sta (dstLo),y
    iny
    sta (dstLo),y
    iny
    lda patLo
    lsr
    lsr
    lsr
    lsr
    tax
    lda niblut,x
    sta (dstLo),y
    iny
    sta (dstLo),y
    iny
    lda patHi
    and #$0f
    tax
    lda niblut,x
    sta (dstLo),y
    iny
    sta (dstLo),y
    iny
    lda patHi
    lsr
    lsr
    lsr
    lsr
    tax
    lda niblut,x
    sta (dstLo),y
    iny
    sta (dstLo),y
    rts

niblut:                       // fat nibble (bit 0 at left) -> doubled row byte
    .byte $00,$c0,$30,$f0,$0c,$cc,$3c,$fc,$03,$c3,$33,$f3,$0f,$cf,$3f,$ff

JCOUNT:
    .byte 0
jointOverflow:
    .byte 0
JOINTT:
    .fill 55*2, 0
.assert "Animation and join code fit below the sine tables", * <= $0e00, true

* = $0e00 "Vertical sine displacement tables"
waveY1:
    .import binary "build/wave-y1.bin"
waveY2:
    .import binary "build/wave-y2.bin"

// Split the triangular Q8 slope table across the two free memory regions.
// Row pointers hide the split. Diagonals have their own direct drawing path.
.function TriangularOffset(span) {
    .return span*(span-1)/2
}
.function SlopeRow(span) {
    .return span <= SHORT_DELTA ? shortRates + TriangularOffset(span) : longRates + TriangularOffset(span) - TriangularOffset(SHORT_DELTA+1)
}
.macro EmitSlopeRows(first, last) {
    .for (var span=first; span<=last; span++) {
        .fill span, floor((256*i + floor(span/2))/span)
    }
}
slopeRowLo:
    .fill MAX_DELTA+1, <SlopeRow(i)
slopeRowHi:
    .fill MAX_DELTA+1, >SlopeRow(i)
shortRates:
    EmitSlopeRows(1, SHORT_DELTA)
.assert "Slope tables fit below the first font", * <= CHARSET, true

* = CHARSET "First character bank"
    .import binary "build/charset.bin"
* = $2800 "Horizontal sine displacement tables"
waveX1:
    .import binary "build/wave-x1.bin"
waveX2:
    .import binary "build/wave-x2.bin"
* = CHARSET_B "Second character bank"
    .import binary "build/charset.bin"
* = charFirst "First character of each line block"
    .import binary "build/char-first.bin"
* = charSecond "Second character of each line block"
    .import binary "build/char-second.bin"
* = charTransform "Reflected and transposed line glyphs"
    .import binary "build/char-transform.bin"
* = charSlope "Block shapes by slope"
    .import binary "build/char-slope.bin"

.import source "char_walk.asm"

* = $7400 "Glyph dictionary"
REVLO:
    .import binary "build/revlo.bin"
REVHI:
    .import binary "build/revhi.bin"
HASHKL:
    .import binary "build/hashkl.bin"
HASHKH:
    .import binary "build/hashkh.bin"
HASHV:
    .import binary "build/hashv.bin"
HASH_DISP_LO:
    .import binary "build/hash-disp-lo.bin"
HASH_DISP_HI:
    .import binary "build/hash-disp-hi.bin"

longRates:
    EmitSlopeRows(SHORT_DELTA+1, MAX_DELTA)
.assert "Long-segment slope table stays below I/O", * <= $d000, true
