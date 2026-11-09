// Bounded direct-mapped normalized edge curves. Cache misses still execute the
// live rational DDA in raster.asm and account for every generated sample.
.const EDGE_CACHE_SLOTS = 64
.const EDGE_CACHE_CURVE_LENGTH = 24
.const EDGE_CACHE_RAM = $e000
.const EDGE_CACHE_CURVES = EDGE_CACHE_RAM + EDGE_CACHE_SLOTS*4
.const EDGE_CACHE_SCRATCH = EDGE_CACHE_CURVES + EDGE_CACHE_SLOTS*EDGE_CACHE_CURVE_LENGTH
.const EDGE_CACHE_STATE_BYTES = EDGE_CACHE_SLOTS*28 + 128
.label edge_cache_valid = EDGE_CACHE_RAM
.label edge_cache_dx = EDGE_CACHE_RAM + EDGE_CACHE_SLOTS
.label edge_cache_dy = EDGE_CACHE_RAM + EDGE_CACHE_SLOTS*2
.label edge_cache_phase = EDGE_CACHE_RAM + EDGE_CACHE_SLOTS*3

.assert "Private cache state must not overlap hardware vectors", EDGE_CACHE_SCRATCH+128 <= $fffa, true

* = $c000 "Normalized edge-cache helpers"
delta_init:
    lda #0
    ldx #0
!clear:
    // Clearing a full page initializes every valid tag, including smaller caches.
    sta edge_cache_valid,x
    inx
    bne !clear-
    lda #1
    sta edge_cache_ready
    rts

edge_cache_lookup:
    lda #0
    sta edge_cache_position
    lda raster_edge_end
    sec
    sbc raster_edge_first
    cmp #EDGE_CACHE_CURVE_LENGTH+1
    bcc !cacheable+
    // An oversized edge executes the same live DDA, writing only disposable
    // scratch. Never publish an incomplete curve as a reusable cache entry.
    lda #<EDGE_CACHE_SCRATCH
    sta edge_cache_ptr
    lda #>EDGE_CACHE_SCRATCH
    sta edge_cache_ptr+1
    clc
    rts
!cacheable:
    lda raster_y0
    and #7
    ldx raster_negative
    beq !positive+
    ora #8
!positive:
    sta edge_cache_phase_key
    eor raster_dx
    eor raster_dy
    and #EDGE_CACHE_SLOTS-1
    tax
    lda edge_curve_pointer_lo,x
    sta edge_cache_ptr
    lda edge_curve_pointer_hi,x
    sta edge_cache_ptr+1
    lda edge_cache_valid,x
    beq !miss+
    lda edge_cache_dx,x
    cmp raster_dx
    bne !miss+
    lda edge_cache_dy,x
    cmp raster_dy
    bne !miss+
    lda edge_cache_phase,x
    cmp edge_cache_phase_key
    bne !miss+

    // A hit translates its relative curve and updates the current face's
    // exact min/max crossings. No ratio initialization or DDA advance occurs.
    ldx raster_edge_first
    ldy #0
!sample:
    lda (edge_cache_ptr),y
    clc
    adc raster_x0
    cmp span_left,x
    bcs !not_left+
    sta span_left,x
!not_left:
    cmp span_right,x
    bcc !not_right+
    sta span_right,x
!not_right:
    iny
    inx
    cpx raster_edge_end
    bcc !sample-
    stx raster_edge_sample
    sec
    rts

!miss:
    lda raster_dx
    sta edge_cache_dx,x
    lda raster_dy
    sta edge_cache_dy,x
    lda edge_cache_phase_key
    sta edge_cache_phase,x
    lda #1
    sta edge_cache_valid,x
    clc
    rts

edge_cache_ready: .byte 0
edge_curve_pointer_lo:
    .fill EDGE_CACHE_SLOTS, <(EDGE_CACHE_CURVES+i*EDGE_CACHE_CURVE_LENGTH)
edge_curve_pointer_hi:
    .fill EDGE_CACHE_SLOTS, >(EDGE_CACHE_CURVES+i*EDGE_CACHE_CURVE_LENGTH)

.assert "Edge-cache helper code must remain below I/O", * <= $d000, true
