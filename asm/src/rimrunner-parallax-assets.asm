// Prepared from the recorded Rimrunner gameplay RAM. The original source stays unchanged.
// asm/tools/prepare-rimrunner-parallax.py validates and describes each source asset.
.var farData = LoadBinary("../build/rimrunner-parallax-data/charset-0.bin")
.var nearData = LoadBinary("../build/rimrunner-parallax-data/charset-1.bin")
.var originalHeaderData = LoadBinary("../build/rimrunner-parallax-data/charset-2.bin")
.var actorData = LoadBinary("../build/rimrunner-parallax-data/mounted-frames.bin")
.var actorOffsets = LoadBinary("../build/rimrunner-parallax-data/mounted-offsets.bin")
.var mapData = LoadBinary("../build/rimrunner-parallax-data/screen.bin")
.var colorData = LoadBinary("../build/rimrunner-parallax-data/color.bin")

.assert "Far charset size", farData.getSize(), 2048
.assert "Near charset size", nearData.getSize(), 2048
.assert "Original HUD charset size", originalHeaderData.getSize(), 2048
.assert "Eight mounted poses with eight sprite slots", actorData.getSize(), 4096
.assert "Eight sprite coordinate pairs", actorOffsets.getSize(), 16
.assert "World screen size", mapData.getSize(), 1000
.assert "World Color RAM size", colorData.getSize(), 1000

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
* = $8000 "Original looping world screen"
worldMap:
    .fill 1000, mapData.get(i)
* = $8400 "Original world colors"
worldColors:
    .fill 1000, colorData.get(i) & 15
* = $8800 "Mounted sprite offsets"
mountedOffsets:
    .fill 16, actorOffsets.get(i)
