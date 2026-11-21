// Double-buffered hires character renderer for Megaplot and Line Scroller.
#if LINE_SCROLLER
.const ASSET_DIR = cmdLineVars.get("assets")
#else
.const ASSET_DIR = "build"
.const SEGMENTS = cmdLineVars.get("segments").asNumber()
.const NODES = SEGMENTS + 1
.assert "Megaplot supports 4 through 56 segments", SEGMENTS >= 4 && SEGMENTS <= 56, true
#endif
.const SHOW_NOICE = cmdLineVars.get("background") == "noice"
// The X waves span 156 logical pixels. The Y waves span 96.
.const MAX_DELTA = 156
.const SHORT_DELTA = 80

.const SCREEN = $0400
.const SCREEN_B = $2c00
.const CHARSET = $2000
.const CHARSET_B = $3000
.const packedFirst = $4000
.const packedSecond = $4800
.const shortDecisionBits = $5e00
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
    .if (SHOW_NOICE) {
        jsr clearWaveA
        jsr clearWaveB
    }
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
#if LINE_SCROLLER
    // Latch one raster event per visible field, with IRQ delivery disabled.
    lda #0
    sta $d01a
    lda #64
    sta $d012
    lda #1
    sta $d019
#endif

waveLoop:
    // Each occupied cache bucket is recorded alongside its patch slot.
    // Clear those buckets before resetting the frame's allocator.
    ldy JCOUNT
    beq !patchHashReady+
    dey
    lda #0
!clearPatchHash:
    ldx patchHashTouched,y
    sta patchHash,x
    dey
    bpl !clearPatchHash-
!patchHashReady:
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
#if LINE_SCROLLER
    jsr drawScroller
#else
    // Each node is evaluated once and shared by its adjacent segments.
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

    jsr drawWaveSegments
#endif

    // Wait for the PAL border before switching screen and character set together.
#if LINE_SCROLLER
scWaitField:
    lda $d019
    and #1
    beq scWaitField
#endif
!border:
    bit $d011
    bmi !show+
    lda $d012
    cmp #$30
    bcc !show+
    cmp #$fc
    bcc !border-
!show:
#if LINE_SCROLLER
    lda #1
    sta $d019
#endif
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
#if !LINE_SCROLLER
// Keep the original prefix at its exact angular phases, then extend its end.
.const HEAD_SEGMENTS = SEGMENTS > 48 ? 48 : SEGMENTS
.function NodePhase(i) {
    .return floor(235*(i > HEAD_SEGMENTS ? HEAD_SEGMENTS : i)/HEAD_SEGMENTS)
}
.function TailNode(i) {
    .return i > HEAD_SEGMENTS ? i-HEAD_SEGMENTS : 0
}
xPhase1:
    .fill NODES, (2*NodePhase(i) + 12*TailNode(i) + 32) & 255
xPhase2:
    .fill NODES, (5*NodePhase(i) + 17*TailNode(i) + 11) & 255
yPhase1:
    .fill NODES, (3*NodePhase(i) + 12*TailNode(i) + 53) & 255
yPhase2:
    .fill NODES, (4*NodePhase(i) + 24*TailNode(i)) & 255
nodeX:
    .fill NODES, 0
nodeY:
    .fill NODES, 0
#endif

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
    .if (SHOW_NOICE) {
        jmp restoreNoiceA
    } else {
        ClearWave(SCREEN)
    }
clearWaveB:
    .if (SHOW_NOICE) {
        jmp restoreNoiceB
    } else {
        ClearWave(SCREEN_B)
    }

// ---- vertex-joint composition ----
// jcode = incoming screencode, (jptrLo) = cell. Existing content is ORed
// with the incoming pattern and resolved as: line-bank hash hit -> joint
// patch slot (glyph expanded into chars 201..255) -> overflow fallback.
sjCompose:
    .if (SHOW_NOICE) {
        tay
        ldx jcode
        lda REVLO,x
        ora REVLO,y
        sta patLo
        lda REVHI,x
        ora REVHI,y
        sta patHi
        cmp REVHI,y
        bne !changed+
        lda patLo
        cmp REVLO,y
        bne !changed+
        rts                    // All incoming pixels already belong to this cell.
    !changed:
    } else {
        tax
        lda REVLO,x
        sta patLo
        lda REVHI,x
        sta patHi
        ldx jcode
        lda REVLO,x
        ora patLo
        sta patLo
        lda REVHI,x
        ora patHi
        sta patHi
    }
    jsr hashLookup            // already a line glyph?
    bne sjStore
    // Both pattern bytes must match. A different key continues probing.
    ldy hidx
sjScan:
    ldx patchHash,y
    beq sjAlloc
    lda patLo
    cmp REVLO,x
    bne sjNext
    lda patHi
    cmp REVHI,x
    bne sjNext
    txa
    jmp sjStore
sjNext:
    iny
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
    .if (SHOW_NOICE) {
        rts                   // Retain the background and any lines already merged.
    } else {
        lda jcode             // With a blank template, keep the newest stamp.
        jmp sjStore
    }
sjPlace:
    ldx JCOUNT
    tya
    sta patchHashTouched,x
    txa
    clc
    adc #201
    sta patchHash,y
    tay
    lda patLo
    sta REVLO,y
    lda patHi
    sta REVHI,y
    inc JCOUNT
    tya
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
    ldy patchOffsetLo,x
    lda drawCharsetHi
    cmp #>CHARSET
    bne !bankB+
    cpx #224-201
    bcs !hiA+
    jmp patchRowsA6
!hiA:
    jmp patchRowsA7
!bankB:
    cpx #224-201
    bcs !hiB+
    jmp patchRowsB6
!hiB:
    jmp patchRowsB7

JCOUNT:
    .byte 0
jointOverflow:
    .byte 0
.assert "Animation and join code fit below the sine tables", * <= $0e00, true

* = $0e00 "Vertical sine displacement tables"
waveY1:
    .import binary ASSET_DIR + "/wave-y1.bin"
waveY2:
    .import binary ASSET_DIR + "/wave-y2.bin"

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
    .import binary ASSET_DIR + "/charset.bin"
* = $2800 "Horizontal sine displacement tables"
waveX1:
    .import binary ASSET_DIR + "/wave-x1.bin"
waveX2:
    .import binary ASSET_DIR + "/wave-x2.bin"
* = CHARSET_B "Second character bank"
    .import binary ASSET_DIR + "/charset.bin"
* = packedFirst "First character of each oriented line block"
    .import binary ASSET_DIR + "/char-packed-first.bin"
* = packedSecond "Second character of each oriented line block"
    .import binary ASSET_DIR + "/char-packed-second.bin"
* = charSlope "Block shapes by slope"
    .import binary ASSET_DIR + "/char-slope.bin"

.import source "char_walk.asm"

* = shortDecisionBits "Short-line Q8 decision bits"
    .import binary ASSET_DIR + "/char-short-decisions.bin"
    .import source "short_decision_stream.asm"
.assert "Short decision walker fits before slope tables", * <= charSlope, true

* = $7400 "Glyph dictionary"
REVLO:
    .import binary ASSET_DIR + "/revlo.bin"
REVHI:
    .import binary ASSET_DIR + "/revhi.bin"
HASHKL:
    .import binary ASSET_DIR + "/hashkl.bin"
HASHKH:
    .import binary ASSET_DIR + "/hashkh.bin"
HASHV:
    .import binary ASSET_DIR + "/hashv.bin"
HASH_DISP_LO:
    .import binary ASSET_DIR + "/hash-disp-lo.bin"
HASH_DISP_HI:
    .import binary ASSET_DIR + "/hash-disp-hi.bin"

longRates:
    EmitSlopeRows(SHORT_DELTA+1, MAX_DELTA)
.assert "Long-segment slope table stays below I/O", * <= $d000, true

.assert "Long-segment rates fit before wave start lookups", * <= $a200, true
* = $a200 "Wave start column lookup"
waveStartColumn:
    .fill 160, i >> 2
* = $a300 "Wave start row lookup"
waveStartRowLo:
    .fill 100, <((i >> 2) * 40)
waveStartRowHi:
    .fill 100, >((i >> 2) * 40)

#if !LINE_SCROLLER
// Generate one call per edge. Reuse the previous endpoint as the start.
* = $c400 "Wave segment dispatch"
drawWaveSegments:
    lda nodeX
    sta lx0
    lda nodeY
    sta ly0
    .for (var next=1; next<=SEGMENTS; next++) {
        lda nodeX + next
        sta lx1
        lda nodeY + next
        sta ly1
        jsr drawCharLine
        .if (next < SEGMENTS) {
            lda lx1
            sta lx0
            lda ly1
            sta ly0
        }
    }
    rts
.assert "Wave dispatch fits before I/O", * <= $d000, true
#endif

* = $b800 "Hash cache for current frame's patch glyphs"
patchHash:
    .fill 256, 0               // Patched glyph code, or zero when empty.
patchHashTouched:
    .fill 55, 0                // Occupied cache bucket for each patch slot.

* = $b200 "Expanded patch rows"
.function ExpandPatchNibble(nibble) {
    .return (nibble & 1) * $c0 + ((nibble >> 1) & 1) * $30 + ((nibble >> 2) & 1) * $0c + ((nibble >> 3) & 1) * $03
}
patchRowLower:
    .fill 256, ExpandPatchNibble(i & 15)
patchRowUpper:
    .fill 256, ExpandPatchNibble(i >> 4)

* = $b400 "Low-byte patch glyph offsets"
patchOffsetLo:
    .fill 55, <((i + 201) * 8)
// Each absolute-indexed store addresses its own glyph row.
.macro WritePatchRows(base) {
    ldx patLo
    lda patchRowLower,x
    sta base,y
    sta base+1,y
    lda patchRowUpper,x
    sta base+2,y
    sta base+3,y
    ldx patHi
    lda patchRowLower,x
    sta base+4,y
    sta base+5,y
    lda patchRowUpper,x
    sta base+6,y
    sta base+7,y
    rts
}
patchRowsA6:
    WritePatchRows(CHARSET + $600)
patchRowsA7:
    WritePatchRows(CHARSET + $700)
patchRowsB6:
    WritePatchRows(CHARSET_B + $600)
patchRowsB7:
    WritePatchRows(CHARSET_B + $700)
.assert "Patch tables and stores fit below the next free bank", * <= $b600, true

.import source "noice_restore.asm"

#if LINE_SCROLLER
#import "../line-scroller/scroller.asm"
#endif
