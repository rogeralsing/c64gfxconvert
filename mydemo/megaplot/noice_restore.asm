// Encode the full screen template as grouped immediate loads and stores.
// Both generated kernels restore all 1000 character cells.
.label restoreNoiceA = $5000
.label restoreNoiceB = $a400

.macro RestoreNoice(screen, template) {
    .var restoredCells = 0
    .for (var glyph=0; glyph<=200; glyph++) {
        .var loaded = false
        .for (var cell=0; cell<1000; cell++) {
            .if ((template.get(cell) & $ff) == glyph) {
                .if (!loaded) {
                    lda #glyph
                    .eval loaded = true
                }
                sta screen + cell
                .eval restoredCells += 1
            }
        }
    }
    .assert "NOICE uses only static glyph codes", restoredCells == 1000, true
    rts
}

.if (SHOW_NOICE) {
    .var noiceTemplate = LoadBinary("build/noice/background.bin")
    .assert "NOICE covers 40×25 character cells", noiceTemplate.getSize() == 1000, true

    * = restoreNoiceA "NOICE screen A restore"
    RestoreNoice(SCREEN, noiceTemplate)
    .assert "NOICE screen A restore fits before short-line decisions", * <= shortDecisionBits, true

    * = restoreNoiceB "NOICE screen B restore"
    RestoreNoice(SCREEN_B, noiceTemplate)
    .assert "NOICE screen B restore fits before patch rows", * <= $b200, true
}
