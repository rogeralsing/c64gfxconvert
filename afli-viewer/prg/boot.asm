// Standalone startup for the pinned GoDot PAL raster engine in static hires mode.
// The outer PRG stages the same AFLI screens and bitmap twice.
* = $2000 "Standalone AFLI startup"

.const source = $fb
.const destination = $fd
.const remaining = $f9

start:
    sei
    cld
    lda #$2f
    sta $00
    lda #$37
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $d01a
    sta $d015
    sta $d020
    lda #$0f
    sta $d019
    lda $dd02
    ora #3
    sta $dd02
    lda #$35
    sta $01
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb

    // Copy backwards: the destination overlaps the end of the staged phase.
    // All RAM must be visible for reads beneath BASIC and writes beneath I/O.
    lda #$34
    sta $01
    lda #<$c38b
    sta source
    lda #>$c38b
    sta source + 1
    lda #<$ffa3
    sta destination
    lda #>$ffa3
    sta destination + 1
    lda #<$3fa4
    sta remaining
    lda #>$3fa4
    sta remaining + 1
    ldy #0
copy:
    lda (source),y
    sta (destination),y
    lda source
    bne decrementSource
    dec source + 1
decrementSource:
    dec source
    lda destination
    bne decrementDestination
    dec destination + 1
decrementDestination:
    dec destination
    lda remaining
    bne decrementRemaining
    dec remaining + 1
decrementRemaining:
    dec remaining
    lda remaining
    ora remaining + 1
    bne copy

    // Build the original raster routine, then enable the identical-bank static display.
    lda #$35
    sta $01
    jsr $0dc6
    jsr $0e3f
display:
    jmp display

nmi:
    rti

// Retargeting the engine's existing JSR here adds exactly 20 entry cycles.
// JMP preserves its return address, so the speedcode RTS returns to the IRQ.
* = $2090 "AFLI raster-entry delay"
timingShim:
    .fill 7, $ea   // Seven two-cycle NOPs = 14 cycles.
    bit $02       // Three cycles; read ordinary zero-page RAM without side effects.
    jmp $8400     // Three cycles; total additional delay = 20 cycles.
