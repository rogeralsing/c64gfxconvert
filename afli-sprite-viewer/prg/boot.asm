// Experimental eight-sprite AFLI startup. Uses the pinned MIT GoDot IRQ wrapper.
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
    jsr prepareSprites
    jsr $0e3f
display:
    jmp display

nmi:
    rti

// The pinned IRQ calls this fixed-address trampoline once per frame.
* = $2090 "Sprite AFLI IRQ entry"
timingShim:
    jmp rasterPreamble

* = $2200 "Sprite AFLI initial full badline"
rasterPreamble:
    inc $02f0                 // Frame counter; outside the timed row kernel.
    lda #52                   // Y31's active sprites will restart at Y52.
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
    lda #$38                  // Natural first badline R48 resets RC before c14.
    sta $d011
    lda #$08                  // First source row uses screen matrix zero.
    sta $d018
    // ENTRY_DELAY
    jmp rasterRows

* = $2400 "Sprite setup"
prepareSprites:
    jsr $0dc6                 // Retain original preparation, unused generated code.
    lda #0
    sta $02f0
    sta $d017                 // Unexpanded height.
    sta $d01b                 // Sprites in front of the bitmap.
    sta $d01c                 // Monochrome hires sprites.
    sta $d01d                 // Unexpanded width.
    sta $d021
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
    lda #1
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

* = $2800 "Fourteen-cycle sprite AFLI rows"
rasterRows:
    // GENERATED_SCANLINES
