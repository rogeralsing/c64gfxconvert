// PAL AFLI with an arbitrary monochrome sprite raster layer.
// Each VIC bank holds one image half and eight phase-specific sprite pointers.
* = $2000 "Standalone layered AFLI startup"

.const source = $fb
.const destination = $fd
.const remaining = $f9
.const spriteColor = SPRITE_COLOR_VALUE
.const backgroundColor = BACKGROUND_COLOR_VALUE

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

    // Copy backwards because the staging and destination ranges overlap.
    // All 16KB include sprite blocks and pointer tables, not just AFLI bytes.
    lda #$34
    sta $01
    lda #<$c3e7
    sta source
    lda #>$c3e7
    sta source + 1
    lda #<$ffff
    sta destination
    lda #>$ffff
    sta destination + 1
    lda #<$4000
    sta remaining
    lda #>$4000
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

    // Install vectors after the full-bank relocation has written their RAM.
    lda #$35
    sta $01
    lda #<nmi
    sta $fffa
    lda #>nmi
    sta $fffb
    jsr prepareSprites
    jsr $0e3f
display:
    jmp display

nmi:
    rti

* = $2090 "Layered AFLI IRQ entry"
timingShim:
    jmp rasterPreamble

* = $2200 "Layered AFLI initial full badline"
rasterPreamble:
    inc $02f0
    lda #2
    sta $dd00                 // Start every image with the upper-half bank.
    lda #52
    sta $d001
    sta $d003
    sta $d005
    sta $d007
    sta $d009
    sta $d00b
    sta $d00d
    sta $d00f
    lda #47
waitForPrimingLine:
    cmp $d012
    bne waitForPrimingLine
    lda #$38
    sta $d011
    lda #$08
    sta $d018
    // ENTRY_DELAY
    jmp rasterRows

* = $2400 "Layered sprite setup"
prepareSprites:
    jsr $0dc6
    lda #0
    sta $02f0
    sta $d017
    sta $d01b
    sta $d01c
    sta $d01d
    sta $d021
    .if (backgroundColor != 0) {
        lda #backgroundColor
        sta $d021
    }
    lda #2
    sta $dd00
    lda #$e0
    sta $d010
    lda #136
    sta $d000
    lda #160
    sta $d002
    lda #184
    sta $d004
    lda #208
    sta $d006
    lda #232
    sta $d008
    lda #0
    sta $d00a
    lda #24
    sta $d00c
    lda #48
    sta $d00e
    lda #31
    sta $d001
    sta $d003
    sta $d005
    sta $d007
    sta $d009
    sta $d00b
    sta $d00d
    sta $d00f
    lda #spriteColor
    sta $d027
    sta $d028
    sta $d029
    sta $d02a
    sta $d02b
    sta $d02c
    sta $d02d
    sta $d02e
    lda #$ff
    sta $d015
    rts

* = $2800 "Fourteen-cycle layered AFLI rows"
rasterRows:
    // GENERATED_SCANLINES
