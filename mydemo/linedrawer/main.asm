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

// The clean-junction kernels reserve more space per unrolled block.
.const EXACT_CORNERS = cmdLineVars.containsKey("exactCorners")
.const FIXED_JUNCTION_FONT = cmdLineVars.containsKey("fixedJunctionFont")
.const CLEAN_JUNCTIONS = EXACT_CORNERS || FIXED_JUNCTION_FONT
.const HOLE_UNROLL = CLEAN_JUNCTIONS ? 2 : 4
.const IS_MESH = cmdLineVars.containsKey("mesh")
.const COMPACT_JOINS = cmdLineVars.containsKey("compactJoins")
.const COMPACT_FIRST_PATCH = 234
.const CROSSING_HOLES = cmdLineVars.containsKey("crossingHoles")
.const HOLE_CODE = 201         // predefined blank that marks an occupied cell
.const ONE_CHAR = cmdLineVars.containsKey("oneChar")
.const ONE_CHAR_CODE = 201
.const SHORT_RATE_LIMIT = CROSSING_HOLES ? 56 : 32
.const shortRates = CROSSING_HOLES ? $c600 : $7800
.const shortRateRowLo = shortRates + SHORT_RATE_LIMIT * (SHORT_RATE_LIMIT + 1) / 2
.const shortRateRowHi = shortRateRowLo + SHORT_RATE_LIMIT + 1
.var MESH_VERTEX_COUNT = 8
.var MESH_FACE_COUNT = 6
.var MESH_EDGE_COUNT = 12
.if (IS_MESH) {
    .eval MESH_VERTEX_COUNT = cmdLineVars.get("vertices").asNumber()
    .eval MESH_FACE_COUNT = cmdLineVars.get("faces").asNumber()
    .eval MESH_EDGE_COUNT = cmdLineVars.get("edges").asNumber()
}

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

.label slotLane=$18
.label nextPatch=$19
.label exactOverflow=JCOUNT+1

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
.const RECIP   = $8000
.const SIZEINV = $9900
.const RECIP_FAR = $9a00
.const EDGES   = $b320
.const FACES   = $b338
.const EDGEFACES = $b350
.const REV8    = $b700          // bit-reverse LUT
.const HREV8   = $b800          // swapnib(rev8) LUT
.const PTAB    = $a800          // interleaved projected x/y low bytes
.const PTAB_HI = PTAB + 2 * MESH_VERTEX_COUNT
.assert "Projected points fit before the sine table", PTAB_HI + 2 * MESH_VERTEX_COUNT <= SIN, true
.const MODE    = $0338          // 255=receipt only, 0=free run, N=cube N frames
.const CDONE   = $033a          // cube halt signature ($c4 $c5 $c6)
.var CAMERA_DEPTH = 16 * 256    // center of the 4–28 unit cube sweep
.var CAMERA_SWEEP = 12 * 256
.var MOTION_X = 320
.var MOTION_Y = 176
.var NEAR_KEY_PHASE = 192      // sine = -1
.if (IS_MESH) {
    .eval CAMERA_DEPTH = 4.25 * 256  // 3.5–5 units keeps each grid readable
    .eval CAMERA_SWEEP = 0.75 * 256
    .eval MOTION_X = 64
    .eval MOTION_Y = 64
    .if (cmdLineVars.get("mesh") == "globe") {
        .eval NEAR_KEY_PHASE = 208  // give the denser grid room for its joins
    }
}
.if (CROSSING_HOLES) {
    .eval CAMERA_DEPTH = cmdLineVars.get("cameraDepth").asNumber()
    .eval CAMERA_SWEEP = cmdLineVars.get("cameraSweep").asNumber()
    .eval MOTION_Y = cmdLineVars.get("motionY").asNumber()
}
.const DEPTH_MIN = 352
.const DEPTH_NEAR_MAX = 2503
.const DEPTH_MAX = 40 * 256 - 1
.const RECIP_FAR_BASE = RECIP_FAR - 2 * floor(DEPTH_NEAR_MAX / 16)
.const SIZE_MIN = 48            // Q6 object scale: 0.75
.const SIZE_ONE = 64
.const SIZE_MAX = 80            // Q6 object scale: 1.25

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
// Reuse the original pixel drawer's scratch space during face culling.
.label faceDxA=psx
.label faceDyA=pdx
.label faceDxB=pdyH
.label faceDyB=pys
.label faceOffset=$80
.label faceBit=$81
.label visibleFaces=$82
.label faceP0=$83
.label faceP1=$84
.label faceP2=$85
.label faceP3=$86
.label drawCharsetHi=$a8
.label backPair=$a9
.label motionPhaseX=$d6
.label motionPhaseY=$d7
.label motionPhaseZ=$d8
.label cubeSize=$d9
.label motionX=$da
.label motionY=$dc
.label motionDepth=$de
.label inverseSize=$e0
.label qsLeft=$e2
.label qsRight=$e3
.label qsProdLo=$e4
.label qsSavedY=$e5


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

// Expand (patLo,patHi) into the reserve glyph indexed by X.
patchGlyph:
    txa
    clc
    .if (COMPACT_JOINS) { adc #COMPACT_FIRST_PATCH } else { adc #201 }
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
.if (COMPACT_JOINS) {
    .import binary "build/compact-charset.bin"
} else {
    .import binary "build/charset.bin"
}

*=$2800 "Flip maps"
flipTabs:
.if (!CROSSING_HOLES) { .import binary "build/flips.bin" }

*=CHARSET_B "Second character bank"
.if (COMPACT_JOINS) {
    .import binary "build/compact-charset.bin"
} else {
    .import binary "build/charset.bin"
}

.label charFirst = $4000
.label charSecond = $5000
.label charTransform = $6000
.label charSlope = $6800

.if (CROSSING_HOLES) {
    .import source "hole_tables.asm"
} else {
    *=charFirst "First character of each line block"
    .import binary "build/char-first.bin"

    *=charSecond "Second character of each line block"
    .import binary "build/char-second.bin"

    *=charTransform "Character reflection and transpose maps"
    .import binary "build/char-transform.bin"

    *=charSlope "Line block shapes by slope"
    .import binary "build/char-slope.bin"
}

.if (CROSSING_HOLES) { .import source "hole_line_setup.asm" }
.import source "char_walk.asm"
.import source "clip_line.asm"
.if (IS_MESH) {
    .import source "mesh_rotate.asm"
} else {
    .import source "cube_grouped.asm"
}
.import source "cube_project.asm"


.if (!COMPACT_JOINS) {
    *=HASHKL "Glyph lookup keys low"
    hashkl:
    .if (!CROSSING_HOLES) { .import binary "build/hashkl.bin" }

    *=HASHKH "Glyph lookup keys high"
    hashkh:
    .if (!CROSSING_HOLES) { .import binary "build/hashkh.bin" }
}

*=HASHV "Glyph lookup codes"
hashv:
.if (!CROSSING_HOLES) { .import binary "build/hashv.bin" }

*=HASH_DISP_LO "Glyph lookup displacements low"
.if (!CROSSING_HOLES) { .import binary "build/hash-disp-lo.bin" }

*=HASH_DISP_HI "Glyph lookup displacements high"
.if (!CROSSING_HOLES) { .import binary "build/hash-disp-hi.bin" }

*=$a200 "Pattern reverse map"
revlo:
.if (!CROSSING_HOLES) { .import binary "build/revlo.bin" }

*=$a300
revhi:
.if (!CROSSING_HOLES) { .import binary "build/revhi.bin" }

*=$a700 "Joint slots"
jointt:
.fill 110, 0



// ================================================================ cube
*=$1200 "Cube code"
// signed 16x16 -> 32-bit prod; clobbers A,X, m_a, m_b
mul16s:
    // Original cube coordinates are ±1 in 8.8 fixed point. Their
    // products are a signed shift, including the full 32-bit sign.
    lda m_a
    bne mul16General
    lda m_a+1
    cmp #1
    beq mul16PositiveUnit
    cmp #$ff
    bne mul16General
    lda #0
    sta prod
    sec
    sbc m_b
    sta prod+1
    lda #0
    sbc m_b+1
    sta prod+2
    lda #0
    bit m_b+1
    bmi !extendNegative+
    sbc #0
    sta prod+3
    rts
!extendNegative:
    sbc #$ff
    sta prod+3
    rts
mul16PositiveUnit:
    lda #0
    sta prod
    lda m_b
    sta prod+1
    lda m_b+1
    sta prod+2
    lda #0
    bit m_b+1
    bpl !extend+
    lda #$ff
!extend:
    sta prod+3
    rts
mul16General:
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
    jsr mul16Unsigned
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

// transform 8 vertices into PTAB and PTAB_HI; integer-exact vs cube_model.py
transformVerts:
    .if (IS_MESH) {
        jsr meshRotate
        lda #<meshRotated
        sta vPtr
        lda #>meshRotated
        sta vPtr+1
    } else {
        jsr groupedRotate
        lda #<groupedVertices
        sta vPtr
        lda #>groupedVertices
        sta vPtr+1
    }
    lda #<PTAB
    sta pPtr
    lda #>PTAB
    sta pPtr+1
    lda #MESH_VERTEX_COUNT
    sta vcount
tvLoop:
    ldy #0
    lda (vPtr),y
    sta rx2
    iny
    lda (vPtr),y
    sta rx2+1
    iny
    lda (vPtr),y
    sta ry2
    iny
    lda (vPtr),y
    sta ry2+1
    iny
    lda (vPtr),y
    sta rz2
    iny
    lda (vPtr),y
    sta rz2+1
    // Depth includes the cube's camera-space position on Z.
    lda motionDepth
    clc
    adc rz2
    sta dtmp
    lda motionDepth+1
    adc rz2+1
    sta dtmp+1
    sec
    lda dtmp
    sbc #<DEPTH_MIN
    lda dtmp+1
    sbc #>DEPTH_MIN
    bcs tvNoLo
    lda #<DEPTH_MIN
    sta dtmp
    lda #>DEPTH_MIN
    sta dtmp+1
tvNoLo:
    lda dtmp
    cmp #<(DEPTH_NEAR_MAX + 1)
    lda dtmp+1
    sbc #>(DEPTH_NEAR_MAX + 1)
    bcs tvFar
    // m_b = RECIP[(d - DEPTH_MIN) * 2]
    lda dtmp
    sec
    sbc #<DEPTH_MIN
    sta m_b
    lda dtmp+1
    sbc #>DEPTH_MIN
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
    jmp tvReadReciprocal
tvFar:
    // At distance a 1/16-unit depth bin has less than 0.32% scale error.
    lda dtmp+1
    cmp #>(DEPTH_MAX + 1)
    bcc !bin+
    lda #<DEPTH_MAX
    sta dtmp
    lda #>DEPTH_MAX
    sta dtmp+1
!bin:
    .for (var bit = 0; bit < 3; bit++) {
        lsr dtmp+1
        ror dtmp
    }
    lda dtmp
    and #$fe                   // byte offset 2 * floor(depth / 16)
    clc
    adc #<RECIP_FAR_BASE
    sta dtmp
    lda dtmp+1
    adc #>RECIP_FAR_BASE
    sta dtmp+1
tvReadReciprocal:
    // sx = 80 + (((rx2 + motionX) * r + $8000) >> 16)
    ldy #0
    lda (dtmp),y
    sta m_b
    iny
    lda (dtmp),y
    sta m_b+1
    lda rx2
    clc
    adc motionX
    sta m_a
    lda rx2+1
    adc motionX+1
    sta m_a+1
    jsr projectReciprocalWord
    lda #80
    clc
    adc prod+2
    ldy #0
    sta (pPtr),y
    lda #0
    adc prod+3
    ldy #(PTAB_HI - PTAB)
    sta (pPtr),y
    // sy = 50 - (((ry2 + motionY) * r + $8000) >> 16)
    // The X projection preserved the reciprocal for Y.
    lda ry2
    clc
    adc motionY
    sta m_a
    lda ry2+1
    adc motionY+1
    sta m_a+1
    jsr projectReciprocalWord
    lda #50
    sec
    sbc prod+2
    ldy #1
    sta (pPtr),y
    lda #0
    sbc prod+3
    ldy #(PTAB_HI - PTAB + 1)
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

// Clear only the hidden screen and release that frame's joint slots.
clearScreenJoints:
    lda #0
    sta JCOUNT
    .if (CLEAN_JUNCTIONS) {
        sta exactOverflow
        lda #201
        sta nextPatch
    }
    jmp clearPreviousBox

// Publish both addresses with one VIC register write in the border.
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
    bit $d011                  // PAL lines 256–311 are in the lower border
    bmi !ready+
    lda $d012
    cmp #$30                   // Leave room before the first visible row
    bcc !ready+
    cmp #$fc                   // All 25 rows have finished scanning
    bcc !wait-
!ready:
    rts

// Fetch both components of a projected diagonal with the same indices.
.macro FaceDiagonal(first, last, dx, dy) {
    ldy last
    ldx first
    lda PTAB,y
    sec
    sbc PTAB,x
    sta dx
    lda PTAB_HI,y
    sbc PTAB_HI,x
    sta dx+1
    iny
    inx
    lda PTAB,y
    sec
    sbc PTAB,x
    sta dy
    lda PTAB_HI,y
    sbc PTAB_HI,x
    sta dy+1
}

.macro MultiplyFaceComponents(left, right) {
    lda left
    sta m_a
    lda left+1
    sta m_a+1
    lda right
    sta m_b
    lda right+1
    sta m_b+1
    jsr faceProduct
}

// Projected diagonal components generally fit in an unsigned byte once
// their signs are removed. Keep the full product for wider diagonals.
faceProduct:
    lda m_a+1
    eor m_b+1
    sta sflag
    lda m_b+1
    beq !rightPositive+
    cmp #$ff
    bne !wide+
    lda #0
    sec
    sbc m_b
    beq !wide+
    tax
    jmp !left+
!rightPositive:
    ldx m_b
!left:
    lda m_a+1
    beq !leftPositive+
    cmp #$ff
    bne !wide+
    lda #0
    sec
    sbc m_a
    beq !wide+
    bne !multiply+
!leftPositive:
    lda m_a
!multiply:
    jsr mul8Quarter
    bit sflag
    bmi !negative+
    sta prod+1
    lda qsProdLo
    sta prod
    lda #0
    beq !extend+
!negative:
    tax
    lda #0
    sec
    sbc qsProdLo
    sta prod
    stx qsProdLo
    lda #0
    sbc qsProdLo
    sta prod+1
    lda #0
    sbc #0
!extend:
    sta prod+2
    sta prod+3
    rts
!wide:
    jmp mul16s

// For an outward-wound quad, the cross product of its screen-space
// diagonals is positive when the face is front-facing (screen Y down).
findVisibleFaces:
    lda #0
    sta faceOffset
    .if (!IS_MESH) {
        sta visibleFaces
        lda #1
        sta faceBit
    }
!face:
    ldy faceOffset
    .if (IS_MESH) {
        lda meshFaceP0,y
        sta faceP0
        lda meshFaceP1,y
        sta faceP1
        lda meshFaceP2,y
        sta faceP2
        lda meshFaceP3,y
        sta faceP3
    } else {
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
    }

    FaceDiagonal(faceP0, faceP2, faceDxA, faceDyA)
    FaceDiagonal(faceP1, faceP3, faceDxB, faceDyB)

    // Opposite-signed nonzero products give the winding directly.
    lda faceDxA+1
    eor faceDyB+1
    sta tmp2
    eor faceDyA+1
    eor faceDxB+1
    bpl !products+
    lda faceDxA
    beq !products+
    lda faceDyB
    beq !products+
    lda faceDyA
    beq !products+
    lda faceDxB
    beq !products+
    bit tmp2
    bmi !hidden+
    bpl !visible+

!products:
    MultiplyFaceComponents(faceDxA, faceDyB)
    jsr prodToSm
    MultiplyFaceComponents(faceDyA, faceDxB)
    lda sm
    sec
    sbc prod
    sta tmp
    lda sm+1
    sbc prod+1
    ora tmp
    sta tmp
    lda sm+2
    sbc prod+2
    ora tmp
    sta tmp
    lda sm+3
    sbc prod+3
    bmi !hidden+
    ora tmp
    beq !hidden+
!visible:
    .if (IS_MESH) {
        lda #1
        bne !store+
    } else {
        lda visibleFaces
        ora faceBit
        sta visibleFaces
    }
!hidden:
    .if (IS_MESH) {
        lda #0
    }
!store:
    .if (IS_MESH) {
        ldx faceOffset
        sta meshVisibleFaces,x
        inx
        stx faceOffset
        cpx #MESH_FACE_COUNT
    } else {
        asl faceBit
        lda faceOffset
        clc
        adc #4
        sta faceOffset
        cmp #24
    }
    beq !done+
    jmp !face-
!done:
    rts

.macro SinePosition(amplitude, output) {
    jsr loadSin                // phase in A
    lda #<amplitude
    sta m_a
    lda #>amplitude
    sta m_a+1
    jsr mul16s
    lda prod+1
    sta output
    lda prod+2
    sta output+1
}

// Hold W or S to use the near or far end of the sweep while X/Y and
// rotation continue. The automatic Z phase continues in the background.
readDepthPhase:
    lda #$fd                  // select keyboard row 1
    sta $dc00
    lda $dc01
    ldx #$ff
    stx $dc00
    and #$22                  // W at bit 1, S at bit 5, active low
    cmp #$20
    beq !near+
    cmp #$02
    beq !far+
    lda motionPhaseZ
    rts
!near:
    lda #NEAR_KEY_PHASE
    rts
!far:
    lda #64                   // sine = +1
    rts

updateCubePosition:
    lda motionPhaseX
    SinePosition(MOTION_X, motionX)
    lda motionPhaseY
    SinePosition(MOTION_Y, motionY)
    jsr readDepthPhase
    SinePosition(CAMERA_SWEEP, motionDepth)
    lda motionDepth
    clc
    adc #<CAMERA_DEPTH
    sta motionDepth
    lda motionDepth+1
    adc #>CAMERA_DEPTH
    sta motionDepth+1

    // Divide translations and camera depth by the object scale once.
    // In the perspective ratio this scales the object before translation.
    lda cubeSize
    cmp #SIZE_MIN
    bcs !upper+
    lda #SIZE_MIN
!upper:
    cmp #SIZE_MAX+1
    bcc !size+
    lda #SIZE_MAX
!size:
    sta cubeSize
    cmp #SIZE_ONE
    beq !done+
    sec
    sbc #SIZE_MIN
    asl
    tax
    lda SIZEINV,x
    sta inverseSize
    lda SIZEINV+1,x
    sta inverseSize+1
    ldy #0
!scale:
    lda motionX,y
    sta m_a
    lda motionX+1,y
    sta m_a+1
    lda inverseSize
    sta m_b
    lda inverseSize+1
    sta m_b+1
    jsr mul16s
    lda prod+1
    sta motionX,y
    lda prod+2
    sta motionX+1,y
    iny
    iny
    cpy #6
    bne !scale-
!done:
    rts

// Draw each edge into the hidden screen/charset pair.
cubeMain:
    .if (COMPACT_JOINS) { jsr compactInit }
    .if (ONE_CHAR) {
        lda #$ff
        ldx #7
    !block:
        sta CHARSET + ONE_CHAR_CODE * 8,x
        sta CHARSET_B + ONE_CHAR_CODE * 8,x
        dex
        bpl !block-
    }
    lda #$ff
    sta $dc00
    sta $dc02                  // keyboard rows are outputs
    lda #0
    sta $dc03                  // keyboard columns are inputs
    lda #32
    sta phYaw
    lda #16
    sta phPit
    lda #11
    sta phRol
    lda #0
    sta frmcnt
    sta motionPhaseX
    lda #64
    sta motionPhaseY
    sta cubeSize
    lda #208                   // start near the camera and move away
    sta motionPhaseZ
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
    jsr updateCubePosition
    jsr transformVerts
    jsr findVisibleFaces
    jsr rememberCubeBox
    .if (CROSSING_HOLES) {
        .if (CLEAN_JUNCTIONS) {
            lda thinFound
            beq !clean+
            jsr thinClearOmissions
        !clean:
        }
        lda meshNeedsClip
        bne !clipped+
        .if (CLEAN_JUNCTIONS) {
            jsr thinGate
            lda thinFound
            bne !clipped+
        }
        jsr drawInsideMesh
        jmp meshEdgesDone
    !clipped:
    }
    .if (IS_MESH) { lda #0 } else { lda #12 }
    sta ecount
edgeLoop:
    .if (IS_MESH) {
        ldx ecount
        .if (CLEAN_JUNCTIONS) {
            lda thinSkip,x
            bne !nextEdge+
        }
        ldy meshEdgeFaceA,x
        lda meshVisibleFaces,y
        bne !draw+
        ldy meshEdgeFaceB,x
        lda meshVisibleFaces,y
        beq !nextEdge+
    !draw:
        ldy meshEdgeA,x
    } else {
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
    }
    lda PTAB,y
    sta lx0
    lda PTAB_HI,y
    sta clipX0Hi
    iny
    lda PTAB,y
    sta ly0
    lda PTAB_HI,y
    sta clipY0Hi
    .if (IS_MESH) {
        ldx ecount
        ldy meshEdgeB,x
    } else {
        lda #12
        sec
        sbc ecount
        asl
        tay
        iny
        lda EDGES,y
        asl
        tay
    }
    lda PTAB,y
    sta lx1
    lda PTAB_HI,y
    sta clipX1Hi
    iny
    lda PTAB,y
    sta ly1
    lda PTAB_HI,y
    sta clipY1Hi
    jsr drawClippedLine
!nextEdge:
    .if (IS_MESH) {
        inc ecount
        lda ecount
        cmp #MESH_EDGE_COUNT
    } else {
        dec ecount
    }
    bne edgeLoop
meshEdgesDone:
    .if (CLEAN_JUNCTIONS) { jsr flushJunctions }
    .if (COMPACT_JOINS) { jsr flushCompact }
    jsr showFrame
    inc phYaw
    inc phYaw
    inc phPit
    inc phRol
    inc phRol
    inc phRol
    inc motionPhaseX
    inc motionPhaseX
    inc motionPhaseX
    inc motionPhaseY
    inc motionPhaseY
    inc motionPhaseZ
    inc frmcnt
    lda MODE
    beq cubeFree
    cmp #255
    beq cubeReceiptHalt
    lda frmcnt
    cmp MODE
    bcc cubeFree
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

*=$a900 "Sin"
sintab:
.import binary "build/sin.bin"

*=RECIP "Reciprocal"
reciptab:
.import binary "build/recip.bin"
reciptabEnd:
.assert "Reciprocals fit before glyph lookup", reciptabEnd <= HASHKL, true

*=SIZEINV "Inverse object scales"
.import binary "build/size-inverse.bin"
.assert "Inverse scales fit before far reciprocals", * <= RECIP_FAR, true

*=RECIP_FAR "Far reciprocals in 1/16-unit bins"
.import binary "build/recip-far.bin"
.assert "Far reciprocals fit before glyph masks", * <= REVLO, true

*=$b600 "Bit reverse LUT"
rev8lut:
.if (!CROSSING_HOLES) { .import binary "build/rev8.bin" }

*=$b800 "H reverse LUT"
hrev8lut:
.import binary "build/hrev8.bin"

*=$ab00 "Quarter squares"
quarterSquareLo:
.fill 512, <floor(i * i / 4)
quarterSquareHi:
.fill 512, >floor(i * i / 4)

*=$af00 "Table multiplication"
// Unsigned byte product A * X -> A:qsProdLo.
// The sum and absolute difference have the same parity, so subtracting
// floor((a-b)^2/4) from floor((a+b)^2/4) gives the exact product.
mul8Quarter:
    sta qsLeft
    stx qsRight
    sec
    sbc qsRight
    bcs !difference+
    eor #$ff
    adc #1
!difference:
    tay
    lda qsLeft
    clc
    adc qsRight
    tax
    bcs !upper+
    sec
    lda quarterSquareLo,x
    sbc quarterSquareLo,y
    sta qsProdLo
    lda quarterSquareHi,x
    sbc quarterSquareHi,y
    rts
!upper:
    sec
    lda quarterSquareLo+$100,x
    sbc quarterSquareLo,y
    sta qsProdLo
    lda quarterSquareHi+$100,x
    sbc quarterSquareHi,y
    rts

// Add A:qsProdLo into the two middle bytes of the 32-bit product.
addMiddleProduct:
    tax
    lda qsProdLo
    clc
    adc prod+1
    sta prod+1
    txa
    adc prod+2
    sta prod+2
    lda prod+3
    adc #0
    sta prod+3
    rts

// Combine nonzero high-byte terms with the low-byte product.
mul16Unsigned:
    sty qsSavedY
    lda m_a
    ldx m_b
    jsr mul8Quarter
    sta prod+1
    lda qsProdLo
    sta prod
    lda #0
    sta prod+2
    sta prod+3
    lda m_a+1
    beq !right+
    ldx m_b
    jsr mul8Quarter
    jsr addMiddleProduct
!right:
    ldx m_b+1
    beq !done+
    lda m_a
    jsr mul8Quarter
    jsr addMiddleProduct
    lda m_a+1
    beq !done+
    ldx m_b+1
    jsr mul8Quarter
    tax
    lda qsProdLo
    clc
    adc prod+2
    sta prod+2
    txa
    adc prod+3
    sta prod+3
!done:
    ldy qsSavedY
    rts

*=$b320 "Edges"
edgestab:
.import binary "build/edges.bin"

*=FACES "Cube faces"
.import binary "build/faces.bin"

*=EDGEFACES "Faces adjacent to each edge"
.import binary "build/edgefaces.bin"

.import source "clear_previous_box.asm"
.if (COMPACT_JOINS) {
    .import source "compact_joins.asm"
}
.if (ONE_CHAR || CROSSING_HOLES) {
    *=shortRates "Short-line Q8 rates"
    .for (var span = 1; span <= SHORT_RATE_LIMIT; span++) {
        .fill span, floor((512 * i + span) / (2 * span))
    }
    .assert "Short-line rate rows match pointer base", * == shortRateRowLo, true
    .fill SHORT_RATE_LIMIT + 1, <(shortRates + i * (i - 1) / 2)
    .fill SHORT_RATE_LIMIT + 1, >(shortRates + i * (i - 1) / 2)
    .assert "Short-line rates fit in reserved space", * <= (CROSSING_HOLES ? $ce00 : $7c00), true
}

.if (IS_MESH) {
    *=meshVertexX "Ball vertices, face diagonals and edges"
    .if (cmdLineVars.get("mesh") == "football") {
        .import binary "build/football-mesh.bin"
    } else {
        .import binary "build/globe-mesh.bin"
    }
    .assert "Ball mesh tables match their layout", * == meshVisibleFaces, true
    .fill MESH_FACE_COUNT, 0
    .assert "Ball mesh fits before character tables", * <= $4000, true
}
.label meshVertexX = $3800
.label meshVertexY = meshVertexX + MESH_VERTEX_COUNT / 2
.label meshVertexZ = meshVertexY + MESH_VERTEX_COUNT / 2
.label meshFaceP0 = meshVertexZ + MESH_VERTEX_COUNT / 2
.label meshFaceP1 = meshFaceP0 + MESH_FACE_COUNT
.label meshFaceP2 = meshFaceP1 + MESH_FACE_COUNT
.label meshFaceP3 = meshFaceP2 + MESH_FACE_COUNT
.label meshEdgeA = meshFaceP3 + MESH_FACE_COUNT
.label meshEdgeB = meshEdgeA + MESH_EDGE_COUNT
.label meshEdgeFaceA = meshEdgeB + MESH_EDGE_COUNT
.label meshEdgeFaceB = meshEdgeFaceA + MESH_EDGE_COUNT
.label meshVisibleFaces = meshEdgeFaceB + MESH_EDGE_COUNT

.if (CROSSING_HOLES) {
    .import source "mesh_inside_edges.asm"
}

.if (CROSSING_HOLES) { .import source "hole_unroll.asm" }

.if (CLEAN_JUNCTIONS) { .import source "clean_junctions.asm" }
