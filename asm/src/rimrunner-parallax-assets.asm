// Prepared from the recorded Rimrunner gameplay RAM. The original source stays unchanged.
// The preparation and native-level extraction tools describe each source asset.
.var farData = LoadBinary("../build/rimrunner-levels/set-1/far-charset.bin")
.var nearData = LoadBinary("../build/rimrunner-levels/set-1/near-charset.bin")
.var originalHeaderData = LoadBinary("../build/rimrunner-parallax-data/charset-2.bin")
.var actorData = LoadBinary("../build/rimrunner-parallax-data/mounted-frames.bin")
.var actorOffsets = LoadBinary("../build/rimrunner-parallax-data/mounted-offsets.bin")
.var colorData = LoadBinary("../build/rimrunner-parallax-data/color.bin")
.var nativeBackData = LoadBinary("../build/rimrunner-levels/set-1/background-chars.bin")
.var nativeMiddleIdsData = LoadBinary("../build/rimrunner-levels/set-1/middle-ids.bin")
.var nativeMiddleDefsData = LoadBinary("../build/rimrunner-levels/set-1/middle-defs.bin")
.var nativeNearIdsData = LoadBinary("../build/rimrunner-levels/set-1/near-ids.bin")
.var nativeNearDefsData = LoadBinary("../build/rimrunner-levels/set-1/near-defs.bin")
.var skyScreenAData = LoadBinary("../build/rimrunner-mci-sky/screen-a.bin")
.var skyScreenBData = LoadBinary("../build/rimrunner-mci-sky/screen-b.bin")
.var skyBitmapAData = LoadBinary("../build/rimrunner-mci-sky/bitmap-a.bin")
.var skyBitmapBData = LoadBinary("../build/rimrunner-mci-sky/bitmap-b.bin")
.var skyColorData = LoadBinary("../build/rimrunner-mci-sky/color.bin")
.var skyBackgroundData = LoadBinary("../build/rimrunner-mci-sky/background.bin")

.assert "Far charset size", farData.getSize(), 2048
.assert "Near charset size", nearData.getSize(), 2048
.assert "Original HUD charset size", originalHeaderData.getSize(), 2048
.assert "Eight mounted poses with eight sprite slots", actorData.getSize(), 4096
.assert "Eight sprite coordinate pairs", actorOffsets.getSize(), 16
.assert "World Color RAM size", colorData.getSize(), 1000
.assert "Native background map size", nativeBackData.getSize(), 12 * BACK_COLUMNS
.assert "Native middle map width", nativeMiddleIdsData.getSize() * 4, MIDDLE_COLUMNS
.assert "Native foreground map width", nativeNearIdsData.getSize() * 4, NEAR_COLUMNS
.assert "Complete 4x2 tile definitions", mod(nativeMiddleDefsData.getSize(), 8), 0
.assert "Complete 4x4 tile definitions", mod(nativeNearDefsData.getSize(), 16), 0
.assert "Native map columns and 39-column lookahead fit in one byte", NEAR_COLUMNS + 39 < 256, true
.assert "MCI phase A sky screen size", skyScreenAData.getSize(), SKY_CELLS
.assert "MCI phase B sky screen size", skyScreenBData.getSize(), SKY_CELLS
.assert "MCI phase A sky bitmap size", skyBitmapAData.getSize(), SKY_BITMAP_BYTES
.assert "MCI phase B sky bitmap size", skyBitmapBData.getSize(), SKY_BITMAP_BYTES
.assert "MCI sky Color RAM size", skyColorData.getSize(), SKY_CELLS
.assert "MCI sky background size", skyBackgroundData.getSize(), 1
.assert "MCI sky and world share background zero", skyBackgroundData.get(0), 0

* = $4000 "Parallax screen"
displayScreen:
    .fill 1024, 0
* = $4800 "Rimrunner far charset"
farCharset:
    .fill 2048, farData.get(i)
* = $5000 "Rimrunner road and foreground charset"
nearCharset:
    .fill 2048, nearData.get(i)
* = $5800 "Parallax header charset"
headerCharset:
    // Startup replaces only glyphs 0-127 with the uppercase ROM font.
    .fill 2048, originalHeaderData.get(i)
* = $6000 "Eight mounted Rimrunner running poses"
mountedFrames:
    .fill 4096, actorData.get(i)
.assert "Mounted sprites stay within the selected VIC bank", * <= $8000, true
* = $8000 "Native background and metatile maps, graphics set 1"
nativeBackMap:
    .fill nativeBackData.getSize(), nativeBackData.get(i)
nativeMiddleIds:
    .fill nativeMiddleIdsData.getSize(), nativeMiddleIdsData.get(i)
nativeMiddleDefs:
    .fill nativeMiddleDefsData.getSize(), nativeMiddleDefsData.get(i)
nativeNearIds:
    .fill nativeNearIdsData.getSize(), nativeNearIdsData.get(i)
nativeNearDefs:
    .fill nativeNearDefsData.getSize(), nativeNearDefsData.get(i)
middleDefLow:
    .fill nativeMiddleDefsData.getSize() / 8, <(nativeMiddleDefs + i * 8)
middleDefHigh:
    .fill nativeMiddleDefsData.getSize() / 8, >(nativeMiddleDefs + i * 8)
nearDefLow:
    .fill nativeNearDefsData.getSize() / 16, <(nativeNearDefs + i * 16)
nearDefHigh:
    .fill nativeNearDefsData.getSize() / 16, >(nativeNearDefs + i * 16)
worldColors:
    .fill 1000, colorData.get(i) & 15
mountedOffsets:
    .fill 16, actorOffsets.get(i)
skyColors:
    .fill SKY_CELLS, skyColorData.get(i) & 15
skyBackground:
    .byte skyBackgroundData.get(0)
.assert "Native data remains below phase A sky screen", * <= $8c00, true

* = $8c00 "MCI sky phase A screen"
skyScreenA:
    .fill SKY_CELLS, skyScreenAData.get(i)
* = $a000 "MCI sky phase A bitmap"
skyBitmapA:
    .fill SKY_BITMAP_BYTES, skyBitmapAData.get(i)
* = $b000 "Staged MCI sky phase B bitmap"
skyBitmapBStaged:
    .fill SKY_BITMAP_BYTES, skyBitmapBData.get(i)
.label skyBitmapB = $e000
* = $cc00 "MCI sky phase B screen"
skyScreenB:
    .fill SKY_CELLS, skyScreenBData.get(i)
.assert "Loadable PRG must remain below C64 I/O", * <= $d000, true
