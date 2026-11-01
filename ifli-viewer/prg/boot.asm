// Standalone startup for the original GoDot English PAL IFLI player.
// The outer PRG stages an uncompressed FunPaint II image at $3ff0.
* = $2000 "Standalone IFLI startup"

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

    // Build the original raster routine, then enable its two-phase display.
    lda #$35
    sta $01
    jsr $0dc6
    jsr $0e3f
display:
    jmp display

nmi:
    rti
