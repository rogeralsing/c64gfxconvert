// Interactive font line drawer — general direction/mirror/entry handling.
//
// Everything the drawer needs is tables: snap thresholds (binary-searched,
// cross-product compares), per-direction records (kstart + entry prefixes +
// middle glyph/step streams), screencode flip maps for the mirrored
// quadrants. The walk: stamp start prefix, follow middle cells (glyph + 2-bit
// step each), stamp end prefix (reversed-draw definition, hv-mapped).
//
// v1 scope: diagonal lines only; H/V/dot and same-cell lines return
// unsupported. Direction records ship for the demo directions only, but the
// code path is fully general.

.const CHARSET = $2000
.const FLIPS   = $2800          // identity, h, v, hv (screencode -> screencode)
.const DIRTAB  = $2c00          // quantized: 65 entries
.const THRESH  = $2e10          // quantized: 64 boundaries
.const SCREEN  = $0400
.const SCREEN_B = $2c00
.const CHARSET_B = $3000
.const DONE    = $0334          // progress marker / verifier signature
.const TIMLO   = $0340          // 12 bytes: cycles per demo line (lo)
.const TIMHI   = $0350          // 12 bytes: cycles per demo line (hi)
.const REVLO   = $a200          // screencode -> pattern low  (256)
.const REVHI   = $a300          // screencode -> pattern high (256)
.const HASHKL  = $9100          // glyph lookup keys low  (512)
.const HASHKH  = $9300          // glyph lookup keys high (512)
.const HASHV   = $9500          // glyph lookup codes     (512)
.const HASH_DISP_LO = $9700
.const HASH_DISP_HI = $9800
.const JOINTT  = $a700          // 55 joint slot patterns (words)
.const JCOUNT  = $a770          // allocated joint slots

// A projected edge stays inside the rectangle of its endpoints. Derive
// the cube's clear area from the same 256-frame vertex table it draws.
.var projectedFrames = LoadBinary("build/cube-geometry.bin")
.var cubeLeft = 39
.var cubeRight = 0
.var cubeTop = 24
.var cubeBottom = 0
.for (var point = 0; point < projectedFrames.getSize(); point = point + 2) {
    .var col = projectedFrames.get(point) >> 2
    .var row = projectedFrames.get(point + 1) >> 2
    .if (col < cubeLeft)   { .eval cubeLeft = col }
    .if (col > cubeRight)  { .eval cubeRight = col }
    .if (row < cubeTop)    { .eval cubeTop = row }
    .if (row > cubeBottom) { .eval cubeBottom = row }
}
.assert "Cube clear rectangle stays on screen", cubeLeft >= 0 && cubeRight < 40 && cubeTop >= 0 && cubeBottom < 25, true

BasicUpstart2(start)

.label lx0=$02
.label ly0=$03
.label lx1=$04
.label ly1=$05
.label ldxa=$06
.label ldya=$07
.label lmx=$08
.label lmy=$09                 // $01 / $ff
.label flipLo=$0a
.label flipHi=$0b
.label hvLo=$0c
.label hvHi=$0d
.label recLo=$0e
.label recHi=$0f
.label entLo=$10
.label entHi=$11
.label glyLo=$12
.label glyHi=$13
.label stpLo=$14
.label stpHi=$15
.label scrLo=$16
.label scrHi=$17
.label s0Lo=$18
.label s0Hi=$19
.label e1Lo=$1a
.label e1Hi=$1b
.label ccx=$1c
.label ccy=$1d
.label kcx=$1e
.label kcy=$1f
.label colLo=$20
.label colHi=$21
.label rowLo=$22
.label rowHi=$23
.label tlo=$24
.label tloHi=$25
.label thi=$26
.label thiHi=$27
.label tmid=$28
.label nMid=$29
.label qLo=$2a
.label qHi=$2b
.label prLo=$2c
.label prHi=$2d
.label f1=$2e
.label f2Lo=$2f
.label f2Hi=$30
.label tstep=$31
.label dptrLo=$32
.label dptrHi=$33
.label tmp=$34
.label tmp2=$35
.label vLo=$36
.label vHi=$37
.label tmidHi=$38
.label jcode=$39
.label patLo=$3a
.label patHi=$3b
.label hidx=$3c
.label dstLo=$3d
.label dstHi=$3e
.label jptrLo=$3f
.label jptrHi=$40

.const SIN     = $a900
.const RECIP   = $ab00
.const VERTS   = $b2f0
.const EDGES   = $b320
.const FACES   = $b338
.const EDGEFACES = $b350
.const REV8    = $b700          // bit-reverse LUT
.const HREV8   = $b800          // swapnib(rev8) LUT
.const PTAB    = $a800          // 8 projected points (sx,sy bytes)
.const MODE    = $0338          // 255=receipt only, 0=free run, N=cube N frames
.const CDONE   = $033a          // cube halt signature ($c4 $c5 $c6)
.const CAML    = $80            // 4.5 in 8.8 (1152)
.const CAMH    = $04
.const DMINL   = $c5            // 709
.const DMINH   = $02
.const DMAXL   = $3b            // 1595
.const DMAXH   = $06

.label phYaw=$41
.label phPit=$42
.label phRol=$43
.label sflag=$44
.label m_a=$45
.label m_b=$47
.label prod=$49
.label sm=$4d
.label rx1=$51
.label ry1=$53
.label rz1=$55
.label rx2=$57
.label ry2=$59
.label rz2=$5b
.label vPtr=$5d
.label pPtr=$5f
.label vcount=$72
.label fkind=$7e
.label ecount=$73
.label baseLo=$75
.label baseHi=$76
.label frmcnt=$74
.label psx=$61
.label psy=$62
.label pdx=$63
.label pdyL=$64
.label pdyH=$65
.label pxs=$66
.label pys=$67
.label perr=$68
.label pe2=$6a
.label curCX=$6c
.label curCY=$6d
.label curPatL=$6e
.label curPatH=$6f
.label dtmp=$70
.label faceOffset=$80
.label faceBit=$81
.label visibleFaces=$82
.label faceP0=$83
.label faceP1=$84
.label faceP2=$85
.label faceP3=$86
.label drawCharsetHi=$a8
.label backPair=$a9


*=$0900 "Code"
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
    lda #$03                  // VIC bank 0
    sta $dd00
    lda #$18                  // screen $0400, charset $2000
    sta $d018
    lda #$1b                  // normal text, 25 rows, Y scroll 3
    sta $d011
    lda #$08                  // hires, 40 columns, X scroll 0
    sta $d016
    lda #>CHARSET
    sta drawCharsetHi
    lda #0
    sta $d020
    sta $d021
    ldx #0
    lda #1
!c:  sta $d800,x
    sta $d900,x
    sta $da00,x
    sta $db00,x
    inx
    bne !c-
    lda #0
    sta JCOUNT
    ldx #0
!s:  sta SCREEN,x
    sta SCREEN+$100,x
    sta SCREEN+$200,x
    sta SCREEN+$300,x
    sta SCREEN_B,x
    sta SCREEN_B+$100,x
    sta SCREEN_B+$200,x
    sta SCREEN_B+$300,x
    inx
    bne !s-

    // timer A free-running on phi2 for the cycle receipt
    lda #0
    sta $dc0e
    lda #$ff
    sta $dc04
    sta $dc05
    lda #$11
    sta $dc0e
    lda #1
    sta $dc0e

    lda #<SCREEN
    sta baseLo
    lda #>SCREEN
    sta baseHi
    lda $0339                 // magic: verifier pre-set MODE?
    cmp #$5a
    beq !modeSet+
    lda #0
    sta MODE                  // default: animate the cube
!modeSet:
    jmp bakeDispatch          // the cube IS the demo; receipt loop kept offline
    ldx #0
lineLoop:
    lda lines,x
    sta lx0
    lda lines+1,x
    sta ly0
    lda lines+2,x
    sta lx1
    lda lines+3,x
    sta ly1
    lda $dc04                 // timer snapshot (counts down)
    sta tmp2
    lda $dc05
    sta tmp
    txa
    pha                       // drawLine clobbers X (mul8); keep the line index
    jsr drawCharLine
    pla
    tax
    stx DONE                  // progress marker: 4*lineIndex while running
    sec
    lda tmp2
    sbc $dc04
    sta tmp2                  // lo delta
    lda tmp
    sbc $dc05
    sta tmp                   // hi delta
    txa
    lsr
    tay
    lda tmp2
    sta TIMLO,y
    lda tmp
    sta TIMHI,y
    txa
    clc
    adc #4
    tax
    cpx #4*12
    bne lineLoop

    lda #$c1
    sta DONE
    lda #$c2
    sta DONE+1
    lda #$c3
    sta DONE+2
bakeDispatch:
    lda MODE
    cmp #255
    bne !bake+
    jmp halt
!bake:
    jmp cubeMain
halt:
    jmp halt

lines:
.import binary "build/lines.bin"

// ---------------------------------------------------------------- helpers
mul8:                         // f1 * (f2Lo,f2Hi) -> (prLo,prHi); clobbers f1/f2
    lda #0
    sta prLo
    sta prHi
    ldx #8
!loop:
    lsr f1
    bcc !skip+
    clc
    lda prLo
    adc f2Lo
    sta prLo
    lda prHi
    adc f2Hi
    sta prHi
!skip:
    asl f2Lo
    rol f2Hi
    dex
    bne !loop-
    rts

// A = cell x, tmp2 = cell y  ->  scrLo/scrHi = (baseLo) + y*40 + x
scrAddr:
    sta tmp
    lda #0
    sta vLo
    sta vHi
    lda tmp2
    beq !norow+
    sta vLo
    asl vLo
    rol vHi
    asl vLo
    rol vHi
    asl vLo
    rol vHi                   // v = y*8
    lda vLo
    sta prLo
    lda vHi
    sta prHi
    asl vLo
    rol vHi
    asl vLo
    rol vHi                   // v = y*32
    clc
    lda vLo
    adc prLo
    sta vLo
    lda vHi
    adc prHi
    sta vHi                   // v = y*40
!norow:
    lda vLo
    clc
    adc baseLo
    sta scrLo
    lda vHi
    adc baseHi
    sta scrHi
    lda scrLo
    clc
    adc tmp
    sta scrLo
    bcc !done+
    inc scrHi
!done:
    rts

// ---------------------------------------------------------------- drawer
drawLine:
    lda lx1
    sec
    sbc lx0
    bcs !px+
    eor #$ff
    clc
    adc #1
    sta ldxa
    lda #$ff
    sta lmx
    jmp !dx+
!px:
    sta ldxa
    lda #1
    sta lmx
!dx:
    lda ldxa
    bne !dxok+
    rts
!dxok:
    lda ly1
    sec
    sbc ly0
    bcs !py+
    eor #$ff
    clc
    adc #1
    sta ldya
    lda #$ff
    sta lmy
    jmp !dy+
!py:
    sta ldya
    lda #1
    sta lmy
!dy:
    lda ldya
    bne !dyok+
    rts
!dyok:

    // flip table: FLIPS + kind*256, kind = (mx<0) | (my<0)<<1
    ldx #0
    lda lmx
    bpl !m1+
    inx
!m1:
    lda lmy
    bpl !m2+
    txa
    ora #2
    tax
!m2:
    stx tmp
    sta fkind
    lda #>FLIPS
    clc
    adc tmp
    sta flipHi
    lda #<FLIPS
    sta flipLo
    lda #(>FLIPS)+3           // hv table for the end glyph
    sta hvHi
    lda #<FLIPS
    sta hvLo

    // ---- snap: upper_bound binary search over 64 thresholds ----
    lda #0
    sta tlo
    sta tloHi
    lda #<64
    sta thi
    lda #>64
    sta thiHi
!search:
    lda tlo
    cmp thi
    lda tloHi
    sbc thiHi                 // 16-bit lo < hi test (missing line!)
    bcc !cont+
    jmp searchDone            // lo >= hi -> done
!cont:
    clc
    lda tlo
    adc thi
    sta tmid
    lda tloHi
    adc thiHi
    lsr
    sta tmidHi                // mid >= 256 only in the final steep steps
    ror tmid                  // tmid:tmidHi = (lo+hi)/2 as 16-bit
    // dptr = THRESH + mid*3   (mid*3 = midLo*3 + midHi*$0300)
    lda #0
    sta dptrHi
    lda tmid
    asl
    rol dptrHi
    clc
    adc tmid
    bcc !n1+
    inc dptrHi
!n1:
    clc
    adc #<THRESH
    sta dptrLo
    lda dptrHi
    adc #>THRESH
    sta dptrHi
    lda tmidHi
    beq !n2+
    clc
    lda dptrLo
    adc #$00
    sta dptrLo
    lda dptrHi
    adc #$03
    sta dptrHi
!n2:
    ldy #0
    lda (dptrLo),y            // n
    sta tmp
    iny
    lda (dptrLo),y            // d low
    sta f2Lo
    iny
    lda (dptrLo),y            // d high flag
    beq !noflag+
    lda #1
    sta f2Hi
    jmp !flagged+
!noflag:
    lda #0
    sta f2Hi
!flagged:
    lda ldya
    sta f1
    jsr mul8                  // pr = dya * d
    lda prLo
    sta qLo
    lda prHi
    sta qHi
    lda tmp                   // n
    sta f2Lo
    lda #0
    sta f2Hi
    lda ldxa
    sta f1
    jsr mul8                  // pr = dxa * n
    lda qHi
    cmp prHi
    bcc !below+
    bne !above+
    lda qLo
    cmp prLo
    bcc !below+
!above:
    lda tmid
    clc
    adc #1
    sta tlo
    lda tmidHi
    adc #0
    sta tloHi
    jmp !search-
!below:
    lda tmid
    sta thi
    lda tmidHi
    sta thiHi
    jmp !search-
searchDone:

    // ---- record fetch ----
    lda #0
    sta dptrHi
    lda tlo
    asl
    rol dptrHi
    sta tmp                   // tlo*2 low byte
    lda tloHi
    beq !nohi+
    inc dptrHi
    inc dptrHi
!nohi:
    lda tmp
    clc
    adc #<DIRTAB
    sta dptrLo
    lda dptrHi
    adc #>DIRTAB
    sta dptrHi
    ldy #0
    lda (dptrLo),y
    sta recLo
    iny
    lda (dptrLo),y
    sta recHi
    ora recLo
    bne !recok+
    rts
!recok:

    // ---- end glyph first (reversed draw, complemented entry, hv map) ----
    lda lmx
    bmi !bx+
    lda lx1
    eor #3
    and #3
    jmp !bx2+
!bx:
    lda lx1
    and #3
!bx2:
    lsr
    asl
    sta tmp                    // (ex'>>1)*2
    lda lmy
    bmi !by+
    lda ly1
    eor #3
    and #3
    jmp !by2+
!by:
    lda ly1
    and #3
!by2:
    lsr
    ora tmp
    asl
    tay                        // byte offset of the ENT4 word pointer
    lda recLo
    clc
    adc #2
    sta glyLo
    lda recHi
    adc #0
    sta glyHi
    lda (glyLo),y
    sta e1Lo                  // borrow e1 as scratch (rebuilt later)
    iny
    lda (glyLo),y
    sta e1Hi
    ldy #0
    lda (e1Lo),y              // kstartB
    tay
    lda (e1Lo),y              // prefix screencode at offset k
    tay
    lda (hvLo),y
    pha                       // gend survives the walk on the stack

    // ---- start entry pointer (start snapped to the even lattice) ----
    lda lmx
    bpl !ax+
    lda lx0
    eor #3
    and #3
    jmp !ax2+
!ax:
    lda lx0
    and #3
!ax2:
    lsr
    asl
    sta tmp                    // (ex>>1)*2
    lda lmy
    bpl !ay+
    lda ly0
    eor #3
    and #3
    jmp !ay2+
!ay:
    lda ly0
    and #3
!ay2:
    lsr
    ora tmp                    // + (ey>>1)   [ENT4 ordinal]
    asl
    tay                        // byte offset of the ENT4 word pointer
    lda (glyLo),y              // gly still points at rec+2
    sta entLo
    iny
    lda (glyLo),y
    sta entHi

    // ---- canonical cells ----
    lda lx0
    lsr
    lsr
    sta tmp
    lda lmx
    bpl !c1+
    lda #39
    sec
    sbc tmp
    sta tmp
!c1:
    lda tmp
    sta ccx
    lda ly0
    lsr
    lsr
    sta tmp
    lda lmy
    bpl !c2+
    lda #24
    sec
    sbc tmp
    sta tmp
!c2:
    lda tmp
    sta ccy
    lda lx1
    lsr
    lsr
    sta tmp
    lda lmx
    bpl !c3+
    lda #39
    sec
    sbc tmp
    sta tmp
!c3:
    lda tmp
    sta kcx
    lda ly1
    lsr
    lsr
    sta tmp
    lda lmy
    bpl !c4+
    lda #24
    sec
    sbc tmp
    sta tmp
!c4:
    lda tmp
    sta kcy

    // ---- step vectors ----
    lda lmx
    sta colLo
    bpl !cs+
    lda #$ff
    sta colHi
    jmp !cs2+
!cs:
    lda #0
    sta colHi
!cs2:
    lda lmy
    bmi !cr+
    lda #40
    sta rowLo
    lda #0
    sta rowHi
    jmp !cs3+
!cr:
    lda #$d8
    sta rowLo
    lda #$ff
    sta rowHi
!cs3:

    // ---- screen addresses ----
    lda lx0
    lsr
    lsr
    sta tmp
    lda ly0
    lsr
    lsr
    sta tmp2
    lda tmp
    jsr scrAddr
    lda scrLo
    sta s0Lo
    lda scrHi
    sta s0Hi
    lda lx1
    lsr
    lsr
    sta tmp
    lda ly1
    lsr
    lsr
    sta tmp2
    lda tmp
    jsr scrAddr               // end cell address
    lda scrLo
    sta e1Lo
    lda scrHi
    sta e1Hi

    // walk starts from the start cell address
    lda s0Lo
    sta scrLo
    lda s0Hi
    sta scrHi

    // ---- middle walk ----
    ldy #1
    lda (recLo),y             // N (padded block count, 4-entry layout)
    sta nMid
    lda entLo
    clc
    adc #5
    sta glyLo
    lda entHi
    adc #0
    sta glyHi
    lda glyLo
    clc
    adc nMid
    sta stpLo
    lda glyHi
    adc #0
    sta stpHi
!walk:
    ldy #0
    lda (stpLo),y
    cmp #$ff
    beq !walkDone+
    sta tstep
    and #1
    beq !nc+
    inc ccx
    clc
    lda scrLo
    adc colLo
    sta scrLo
    lda scrHi
    adc colHi
    sta scrHi
!nc:
    lda tstep
    and #2
    beq !nr+
    inc ccy
    clc
    lda scrLo
    adc rowLo
    sta scrLo
    lda scrHi
    adc rowHi
    sta scrHi
!nr:
    // end/overshoot test: stop when ccx>kcx, or ccy>kcy, or exact hit
    lda ccx
    cmp kcx
    bcc !stamp+
    bne !walkDone+
    lda ccy
    cmp kcy
    beq !walkDone+
    bcs !walkDone+
!stamp:
    lda (glyLo),y
    tay
    lda (flipLo),y
    ldy #0
    sta (scrLo),y
    inc glyLo
    bne !g1+
    inc glyHi
!g1:
    inc stpLo
    bne !g2+
    inc stpHi
!g2:
    jmp !walk-
!walkDone:

    // ---- start stamp (skipped when start and end share a cell) ----
    lda lx0
    lsr
    lsr
    sta tmp
    lda ly0
    lsr
    lsr
    sta tmp2
    lda lx1
    lsr
    lsr
    cmp tmp
    bne !stampStart+
    lda ly1
    lsr
    lsr
    cmp tmp2
    beq !stampEnd+
!stampStart:
    ldy #0
    lda (entLo),y             // kstartA
    tay
    lda (entLo),y             // prefix screencode at offset k
    tay
    lda (flipLo),y
    sta jcode
    lda s0Lo
    sta jptrLo
    lda s0Hi
    sta jptrHi
    jsr stampJoint

    // ---- end stamp ----
!stampEnd:
    pla
    tay
    lda (flipLo),y
    sta jcode
    lda e1Lo
    sta jptrLo
    lda e1Hi
    sta jptrHi
    jsr stampJoint
    rts

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
    bne !hit+
    jmp sjTrySlots
!hit:
    jmp sjStore
sjTrySlots:
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

// expand (patLo,patHi) into char 201+slot of the charset; slot index in X
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

*=$2000 "Charset"
charset:
.import binary "build/charset.bin"

*=$2800 "Flip maps"
flipTabs:
.import binary "build/flips.bin"

*=CHARSET_B "Second character bank"
.import binary "build/charset.bin"

*=$4000 "First character of each line block"
charFirst:
.import binary "build/char-first.bin"

*=$5000 "Second character of each line block"
charSecond:
.import binary "build/char-second.bin"

*=$6000 "Character reflection and transpose maps"
charTransform:
.import binary "build/char-transform.bin"

*=$6800 "Line block shapes by slope"
charSlope:
.import binary "build/char-slope.bin"

.import source "char_walk.asm"

*=$8000 "Projected cube vertices"
cubeGeometry:
.import binary "build/cube-geometry.bin"

*=$9000 "Front-facing cube sides"
cubeVisible:
.import binary "build/cube-visible.bin"


*=HASHKL "Glyph lookup keys low"
hashkl:
.import binary "build/hashkl.bin"

*=HASHKH "Glyph lookup keys high"
hashkh:
.import binary "build/hashkh.bin"

*=HASHV "Glyph lookup codes"
hashv:
.import binary "build/hashv.bin"

*=HASH_DISP_LO "Glyph lookup displacements low"
.import binary "build/hash-disp-lo.bin"

*=HASH_DISP_HI "Glyph lookup displacements high"
.import binary "build/hash-disp-hi.bin"

*=$a200 "Pattern reverse map"
revlo:
.import binary "build/revlo.bin"

*=$a300
revhi:
.import binary "build/revhi.bin"

*=$a700 "Joint slots"
jointt:
.fill 110, 0



// ================================================================ cube
*=$1200 "Cube code"
// signed 16x16 -> 32-bit prod; clobbers A,X, m_a, m_b
mul16s:
    lda #0
    sta sflag
    lda m_a+1
    bpl !a+
    inc sflag
    sec
    lda #0
    sbc m_a
    sta m_a
    lda #0
    sbc m_a+1
    sta m_a+1
!a:
    lda m_b+1
    bpl !b+
    inc sflag
    sec
    lda #0
    sbc m_b
    sta m_b
    lda #0
    sbc m_b+1
    sta m_b+1
!b:
    lda #0
    sta prod
    sta prod+1
    sta prod+2
    sta prod+3
    ldx #16
!m:
    lsr m_a+1
    ror m_a
    bcc !s+
    clc
    lda prod+2
    adc m_b
    sta prod+2
    lda prod+3
    adc m_b+1
    sta prod+3
!s:
    lsr prod+3
    ror prod+2
    ror prod+1
    ror prod
    dex
    bne !m-
    lda sflag
    lsr
    bcc !p+
    sec
    lda #0
    sbc prod
    sta prod
    lda #0
    sbc prod+1
    sta prod+1
    lda #0
    sbc prod+2
    sta prod+2
    lda #0
    sbc prod+3
    sta prod+3
!p:
    rts

prodToSm:
    lda prod
    sta sm
    lda prod+1
    sta sm+1
    lda prod+2
    sta sm+2
    lda prod+3
    sta sm+3
    rts
prodAddSm:
    clc
    lda sm
    adc prod
    sta sm
    lda sm+1
    adc prod+1
    sta sm+1
    lda sm+2
    adc prod+2
    sta sm+2
    lda sm+3
    adc prod+3
    sta sm+3
    rts
prodSubSm:
    sec
    lda sm
    sbc prod
    sta sm
    lda sm+1
    sbc prod+1
    sta sm+1
    lda sm+2
    sbc prod+2
    sta sm+2
    lda sm+3
    sbc prod+3
    sta sm+3
    rts

// m_b = SIN[phase]; phase in A
loadSin:
    asl
    tay
    bcs !upper+
    lda SIN,y
    sta m_b
    iny
    lda SIN,y
    sta m_b+1
    rts
!upper:
    lda SIN+$100,y
    sta m_b
    iny
    lda SIN+$100,y
    sta m_b+1
    rts

// transform 8 vertices into PTAB; integer-exact vs cube_model.py
transformVerts:
    lda #<VERTS
    sta vPtr
    lda #>VERTS
    sta vPtr+1
    lda #<PTAB
    sta pPtr
    lda #>PTAB
    sta pPtr+1
    lda #8
    sta vcount
tvLoop:
    // yaw: rx1 = (x*cosY + z*sinY)>>8
    ldy #0
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phYaw
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    ldy #4
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phYaw
    jsr loadSin
    jsr mul16s
    jsr prodAddSm
    lda sm+1
    sta rx1
    lda sm+2
    sta rx1+1
    // rz1 = (z*cosY - x*sinY)>>8
    ldy #4
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phYaw
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    ldy #0
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phYaw
    jsr loadSin
    jsr mul16s
    jsr prodSubSm
    lda sm+1
    sta rz1
    lda sm+2
    sta rz1+1
    // pitch: ry1 = (y*cosX - rz1*sinX)>>8
    ldy #2
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phPit
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    lda rz1
    sta m_a
    lda rz1+1
    sta m_a+1
    lda phPit
    jsr loadSin
    jsr mul16s
    jsr prodSubSm
    lda sm+1
    sta ry1
    lda sm+2
    sta ry1+1
    // rz2 = (y*sinX + rz1*cosX)>>8
    ldy #2
    lda (vPtr),y
    sta m_a
    iny
    lda (vPtr),y
    sta m_a+1
    lda phPit
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    lda rz1
    sta m_a
    lda rz1+1
    sta m_a+1
    lda phPit
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodAddSm
    lda sm+1
    sta rz2
    lda sm+2
    sta rz2+1
    // roll: rx2 = (rx1*cosR - ry1*sinR)>>8
    lda rx1
    sta m_a
    lda rx1+1
    sta m_a+1
    lda phRol
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    lda ry1
    sta m_a
    lda ry1+1
    sta m_a+1
    lda phRol
    jsr loadSin
    jsr mul16s
    jsr prodSubSm
    lda sm+1
    sta rx2
    lda sm+2
    sta rx2+1
    // ry2 = (rx1*sinR + ry1*cosR)>>8
    lda rx1
    sta m_a
    lda rx1+1
    sta m_a+1
    lda phRol
    jsr loadSin
    jsr mul16s
    jsr prodToSm
    lda ry1
    sta m_a
    lda ry1+1
    sta m_a+1
    lda phRol
    clc
    adc #64
    jsr loadSin
    jsr mul16s
    jsr prodAddSm
    lda sm+1
    sta ry2
    lda sm+2
    sta ry2+1
    // d = 1152 + rz2 (16-bit), clamped to [709,1595]
    lda #CAML
    clc
    adc rz2
    sta dtmp
    lda #CAMH
    adc rz2+1
    sta dtmp+1
    sec
    lda dtmp
    sbc #DMINL
    lda dtmp+1
    sbc #DMINH
    bcs tvNoLo
    lda #DMINL
    sta dtmp
    lda #DMINH
    sta dtmp+1
tvNoLo:
    lda dtmp
    sec
    sbc #DMAXL
    lda dtmp+1
    sbc #DMAXH
    bcc tvNoHi
    lda #DMAXL
    sta dtmp
    lda #DMAXH
    sta dtmp+1
tvNoHi:
    // m_b = RECIP[(d-709)*2]
    lda dtmp
    sec
    sbc #DMINL
    sta m_b
    lda dtmp+1
    sbc #DMINH
    sta m_b+1
    asl m_b
    rol m_b+1
    lda m_b
    clc
    adc #<RECIP
    sta dtmp
    lda m_b+1
    adc #>RECIP
    sta dtmp+1
    // sx = 80 + ((rx2*r + $8000)>>16).lo
    ldy #0
    lda (dtmp),y
    sta m_b
    iny
    lda (dtmp),y
    sta m_b+1
    lda rx2
    sta m_a
    lda rx2+1
    sta m_a+1
    jsr mul16s
    clc
    lda prod+1
    adc #$80
    sta prod+1
    lda prod+2
    adc #$00
    sta prod+2
    lda prod+3
    adc #$00
    sta prod+3
    lda #80
    clc
    adc prod+2
    ldy #0
    sta (pPtr),y
    // sy = 50 - ((ry2*r + $8000)>>16).lo
    ldy #0
    lda (dtmp),y
    sta m_b
    iny
    lda (dtmp),y
    sta m_b+1
    lda ry2
    sta m_a
    lda ry2+1
    sta m_a+1
    jsr mul16s
    clc
    lda prod+1
    adc #$80
    sta prod+1
    lda prod+2
    adc #$00
    sta prod+2
    lda prod+3
    adc #$00
    sta prod+3
    lda #50
    sec
    sbc prod+2
    ldy #1
    sta (pPtr),y
    // next vertex
    lda vPtr
    clc
    adc #6
    sta vPtr
    bcc !v+
    inc vPtr+1
!v:
    lda pPtr
    clc
    adc #2
    sta pPtr
    bcc !p2+
    inc pPtr+1
!p2:
    dec vcount
    beq tvDone
    jmp tvLoop
tvDone:
    rts

// direct Bresenham rasterizer: fat pixels -> per-cell patterns -> composed
// stamps. Same bank/joint semantics as the record drawer, no tables needed.
drawSeg:
    lda lx1
    sec
    sbc lx0
    bcc dsNegX
    sta pdx
    lda #1
    sta pxs
    jmp dsXDone
dsNegX:
    eor #$ff
    clc
    adc #1
    sta pdx
    lda #$ff
    sta pxs
dsXDone:
    lda ly1
    sec
    sbc ly0
    bcc dsNegY
    beq dsZeroY
    eor #$ff
    clc
    adc #1
    sta pdyL
    lda #$ff
    sta pdyH
    lda #1
    sta pys
    jmp dsYDone
dsNegY:
    eor #$ff
    clc
    adc #1
    eor #$ff
    clc
    adc #1
    sta pdyL
    lda #$ff
    sta pdyH
    lda #$ff
    sta pys
    jmp dsYDone
dsZeroY:
    lda #0
    sta pdyL
    sta pdyH
    lda #1
    sta pys
dsYDone:
    // rowstep = pys * 40; colstep = sign-extended pxs
    lda pys
    bpl !rs+
    lda #$d8
    sta rowLo
    lda #$ff
    sta rowHi
    jmp !rs2+
!rs:
    lda #40
    sta rowLo
    lda #0
    sta rowHi
!rs2:
    lda pxs
    bpl !cs+
    lda #$ff
    sta colLo
    lda #$ff
    sta colHi
    jmp !cs2+
!cs:
    lda #1
    sta colLo
    lda #0
    sta colHi
!cs2:
    lda pdx
    clc
    adc pdyL
    sta perr
    lda #0
    adc pdyH
    sta perr+1
    lda lx0
    sta psx
    lda ly0
    sta psy
    lda #$ff
    sta curCX
    sta curCY
    lda #0
    sta curPatL
    sta curPatH
dsLoop:
    // cell change check BEFORE plotting this pixel's bit
    lda curCX
    cmp #$ff
    bne dsChk
    jmp dsFirstCell              // first pixel of the line: set the cell
dsChk:
    lda psx
    lsr
    lsr
    cmp curCX
    bne dsNewCell
    lda psy
    lsr
    lsr
    cmp curCY
    beq dsPlot
dsNewCell:
    lda curCX
    cmp #$ff
    beq dsFirstCell
    jsr dsStamp
    lda #0
    sta curPatL
    sta curPatH
    // move jptr to the new cell incrementally
    lda psx
    lsr
    lsr
    sta dtmp
    lda dtmp
    cmp curCX
    beq !nc+
    sta curCX
    clc
    lda jptrLo
    adc colLo
    sta jptrLo
    lda jptrHi
    adc colHi
    sta jptrHi
!nc:
    lda psy
    lsr
    lsr
    cmp curCY
    beq !nr+
    sta curCY
    lda jptrLo
    clc
    adc rowLo
    sta jptrLo
    lda jptrHi
    adc rowHi
    sta jptrHi
    jmp dsPlot2
!nr:
    sta curCY
    jmp dsPlot2
dsFirstCell:
    lda psx
    lsr
    lsr
    sta curCX
    lda psy
    lsr
    lsr
    sta curCY
    sta tmp2
    lda curCX
    jsr scrAddr
    lda scrLo
    sta jptrLo
    lda scrHi
    sta jptrHi
dsPlot2:
dsPlot:
    lda psy
    and #3
    asl
    asl
    sta pe2+1                 // scratch: bit index high part
    lda psx
    and #3
    ora pe2+1
    tay
    lda bitlo,y
    ora curPatL
    sta curPatL
    lda bithi,y
    ora curPatH
    sta curPatH
    lda psx
    cmp lx1
    bne dsStep
    lda psy
    cmp ly1
    bne dsStep
    jmp dsAtEnd
dsStep:
    lda perr
    asl
    sta pe2
    lda perr+1
    rol
    sta pe2+1
    // if e2 >= pdy: x step, perr += pdy
    lda pe2
    sec
    sbc pdyL
    lda pe2+1
    sbc pdyH
    bmi !nox+
    lda psx
    clc
    adc pxs
    sta psx
    lda perr
    clc
    adc pdyL
    sta perr
    lda perr+1
    adc pdyH
    sta perr+1
!nox:
    // if e2 <= pdx: y step, perr += pdx   (e2 signed 16, pdx byte)
    lda pe2+1
    bmi !dy2+
    bne !noy+
    lda pe2
    cmp pdx
    beq !dy2+
    bcs !noy+
!dy2:
    lda psy
    clc
    adc pys
    sta psy
    lda perr
    clc
    adc pdx
    sta perr
    lda perr+1
    adc #0
    sta perr+1
!noy:
    jmp dsLoop
dsAtEnd:
    jsr dsStamp
    rts

// stamp accumulated cell pattern at (jptrLo) with joint composition
dsStamp:
    lda curPatL
    sta patLo
    lda curPatH
    sta patHi
    ldy #0
    lda (jptrLo),y
    bne dspCompose
    jsr hashLookup
    beq dspBad
    sta (jptrLo),y
    rts
dspBad:
    lda #$ee
    sta (jptrLo),y
    rts
dspCompose:
    cmp #201
    bcc dspRev
    sec
    sbc #201
    asl
    tay
    lda JOINTT,y
    sta qLo
    lda JOINTT+1,y
    sta qHi
    jmp dspOr
dspRev:
    tax
    lda REVLO,x
    sta qLo
    lda REVHI,x
    sta qHi
dspOr:
    lda qLo
    ora curPatL
    sta patLo
    lda qHi
    ora curPatH
    sta patHi
    jsr hashLookup
    bne dspStore
    ldx #0
dspScan:
    cpx JCOUNT
    beq dspAlloc
    txa
    asl
    tay
    lda patLo
    cmp JOINTT,y
    bne dspNext
    lda patHi
    cmp JOINTT+1,y
    bne dspNext
    txa
    clc
    adc #201
    jmp dspStore
dspNext:
    inx
    jmp dspScan
dspAlloc:
    lda JCOUNT
    cmp #55
    bcc dspPlace
    lda curPatL
    sta patLo
    lda curPatH
    sta patHi
    jsr hashLookup
    beq dspStore0
    jmp dspStore
dspStore0:
    jmp dspBad
dspPlace:
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
    pha
    jsr patchGlyph
    pla
dspStore:
    ldy #0
    sta (jptrLo),y
    rts

bitlo:
.import binary "build/bitlo.bin"
bithi:
.import binary "build/bithi.bin"

.macro ClearCubeArea(address) {
    ldx #cubeRight-cubeLeft
!clear:
    .for (var row = cubeTop; row <= cubeBottom; row++) {
        sta address + row * 40 + cubeLeft,x
    }
    dex
    bpl !clear-
}

// Clear only the hidden screen and release that frame's joint slots.
clearScreenJoints:
    lda #0
    sta JCOUNT
    ldx backPair
    bne !second+
    ClearCubeArea(SCREEN)
    rts
!second:
    ClearCubeArea(SCREEN_B)
    rts

// Publish both addresses with one VIC register write in the lower border.
showFrame:
    jsr waitFrame
    ldx backPair
    lda vicPairs,x
presentFrame:
    sta $d018
    txa
    eor #1
    sta backPair
    rts

screenPages:
    .byte >SCREEN, >SCREEN_B
charsetPages:
    .byte >CHARSET, >CHARSET_B
vicPairs:
    .byte $18, $bc             // $0400/$2000, $2c00/$3000

waitFrame:
!wait:
    lda $d012
    cmp #$fc                   // PAL lower border, after all 25 rows
    bne !wait-
    rts

// Signed difference A - PTAB[X]. The projected cube spans less than 128
// fat pixels along either axis, so the byte result can be sign-extended.
faceDelta:
    sec
    sbc PTAB,x
    ldx #0
    cmp #$80
    bcc !done+
    dex
!done:
    rts

// For an outward-wound quad, the cross product of its screen-space
// diagonals is positive when the face is front-facing (screen Y down).
findVisibleFaces:
    lda #0
    sta faceOffset
    sta visibleFaces
    lda #1
    sta faceBit
!face:
    ldy faceOffset
    lda FACES,y
    asl
    sta faceP0
    iny
    lda FACES,y
    asl
    sta faceP1
    iny
    lda FACES,y
    asl
    sta faceP2
    iny
    lda FACES,y
    asl
    sta faceP3

    ldx faceP2
    lda PTAB,x
    ldx faceP0
    jsr faceDelta
    sta m_a
    stx m_a+1
    ldx faceP3
    lda PTAB+1,x
    ldx faceP1
    inx
    jsr faceDelta
    sta m_b
    stx m_b+1
    jsr mul16s
    jsr prodToSm

    ldx faceP2
    lda PTAB+1,x
    ldx faceP0
    inx
    jsr faceDelta
    sta m_a
    stx m_a+1
    ldx faceP3
    lda PTAB,x
    ldx faceP1
    jsr faceDelta
    sta m_b
    stx m_b+1
    jsr mul16s
    lda sm
    sec
    sbc prod
    sta tmp
    lda sm+1
    sbc prod+1
    bmi !hidden+
    ora tmp
    beq !hidden+
    lda visibleFaces
    ora faceBit
    sta visibleFaces
!hidden:
    asl faceBit
    lda faceOffset
    clc
    adc #4
    sta faceOffset
    cmp #24
    beq !done+
    jmp !face-
!done:
    rts

// Draw each edge into the hidden screen/charset pair.
cubeMain:
    lda #0
    sta frmcnt
    lda #1                    // pair A is visible at startup
    sta backPair
cubeLoop:
    lda #0
    sta baseLo
    ldx backPair
    lda screenPages,x
    sta baseHi
    lda charsetPages,x
    sta drawCharsetHi
    jsr clearScreenJoints
    jsr loadCubeFrame
    lda #12
    sta ecount
edgeLoop:
    lda #12
    sec
    sbc ecount
    tay
    lda EDGEFACES,y
    and visibleFaces
    beq !nextEdge+
    tya
    asl
    tay
    lda EDGES,y
    asl
    tay
    lda PTAB,y
    sta lx0
    iny
    lda PTAB,y
    sta ly0
    lda #12
    sec
    sbc ecount
    asl
    tay
    iny
    lda EDGES,y
    asl
    tay
    lda PTAB,y
    sta lx1
    iny
    lda PTAB,y
    sta ly1
    jsr drawCharLine           // write precomputed character codes
!nextEdge:
    dec ecount
    bne edgeLoop
    jsr showFrame
    inc frmcnt
    lda MODE
    beq cubeFree
    cmp #255
    beq cubeReceiptHalt
    lda frmcnt
    cmp MODE
    bcc cubeLoop
    lda #$c4
    sta CDONE
    lda #$c5
    sta CDONE+1
    lda #$c6
    sta CDONE+2
    jmp halt
cubeReceiptHalt:
    jmp halt
cubeFree:
    jmp cubeLoop

// The fixed demonstration provides projected vertices and a face mask.
// The character drawer still receives coordinates and draws each line live.
loadCubeFrame:
    lda frmcnt
    asl
    asl
    asl
    asl
    sta pPtr
    lda frmcnt
    lsr
    lsr
    lsr
    lsr
    clc
    adc #>cubeGeometry
    sta pPtr+1
    ldy #15
!point:
    lda (pPtr),y
    sta PTAB,y
    dey
    bpl !point-
    ldx frmcnt
    lda cubeVisible,x
    sta visibleFaces
    rts

*=$a900 "Sin"
sintab:
.import binary "build/sin.bin"

*=$ab00 "Reciprocal"
reciptab:
.import binary "build/recip.bin"

*=$b600 "Bit reverse LUT"
rev8lut:
.import binary "build/rev8.bin"

*=$b800 "H reverse LUT"
hrev8lut:
.import binary "build/hrev8.bin"

*=$b2f0 "Vertices"
vertstab:
.import binary "build/verts.bin"

*=$b320 "Edges"
edgestab:
.import binary "build/edges.bin"

*=FACES "Cube faces"
.import binary "build/faces.bin"

*=EDGEFACES "Faces adjacent to each edge"
.import binary "build/edgefaces.bin"
