// Exact composite MCI pixels and deduplicated original mounted actor graphics.
.var bitmapAData = LoadBinary("../build/rimrunner-mci-composite/bitmap-a.bin")
.var bitmapBData = LoadBinary("../build/rimrunner-mci-composite/bitmap-b.bin")
.var screenAData = LoadBinary("../build/rimrunner-mci-composite/screen-a.bin")
.var screenBData = LoadBinary("../build/rimrunner-mci-composite/screen-b.bin")
.var colorData = LoadBinary("../build/rimrunner-mci-composite/color.bin")
.var backgroundData = LoadBinary("../build/rimrunner-mci-composite/background.bin")
.var actorData = LoadBinary("../build/rimrunner-parallax-data/mounted-unique.bin")
.var actorMapData = LoadBinary("../build/rimrunner-parallax-data/mounted-frame-map.bin")
.var actorOffsets = LoadBinary("../build/rimrunner-parallax-data/mounted-offsets.bin")
.assert "Phase A bitmap", bitmapAData.getSize(), 8000
.assert "Phase B bitmap", bitmapBData.getSize(), 8000
.assert "Phase A screen", screenAData.getSize(), 1000
.assert "Phase B screen", screenBData.getSize(), 1000
.assert "Shared Color RAM", colorData.getSize(), 1000
.assert "Mounted atlas", actorData.getSize(), 2624
.assert "Mounted frame map", actorMapData.getSize(), 56
.assert "Mounted offsets", actorOffsets.getSize(), 16

mountedFrameMap:
    .fill 56, actorMapData.get(i)
mountedOffsets:
    .fill 16, actorOffsets.get(i)
backgroundColor:
    .byte backgroundData.get(0)
.assert "Small runtime assets remain below staging", * <= $2000, true
* = $2000 "Staged phase B bitmap"
stagedBitmapB:
    .fill 8000, bitmapBData.get(i)
* = $4000 "Phase A bitmap, front buffers and static sky"
bitmapA:
    .fill 8000, bitmapAData.get(i)
* = $6000 "Phase A screen"
screenA:
    .fill 1000, screenAData.get(i)
    .fill 24, 0
* = $6400 "Mounted actor atlas, phase A"
actorAtlasA:
    .fill actorData.getSize(), actorData.get(i)
.assert "Actor atlas ends before lower back buffer", * <= $6f00, true
* = $6f00 "Staged phase B screen"
stagedScreenB:
    .fill 1000, screenBData.get(i)
* = $7300 "Staged shared Color RAM"
stagedColors:
    .fill 1000, colorData.get(i) & 15

// Specialized two-column copies form interruptible eight-column jobs and avoid per-byte pointers.
* = $8000 "Bounded world back-buffer copy routines"
.var copyAddresses = List()
.for (var band = 0; band < 3; band++) {
    .for (var phase = 0; phase < 2; phase++) {
        .for (var front = 0; front < 2; front++) {
            .for (var segment = 0; segment < 3; segment++) {
                .eval copyAddresses.add(*)
                .var bank = phase == 0 ? BITMAP_A : BITMAP_B
                .var sourceBase = bank + front * $2000
                .var targetBase = bank + (1 - front) * $2000
                .for (var row = 0; row < BAND_ROW_COUNTS.get(band); row++) {
                    .var offset = (BAND_FIRST_ROWS.get(band) + row) * 320
                    .for (var byte = 0; byte < 16; byte++) {
                        .var source = segment == 0 ? 8 + byte : 264 + byte
                        .var target = segment == 0 ? byte : 256 + byte
                        .if (segment == 2) {
                            .eval source = byte < 8 ? 312 + byte : byte - 8
                            .eval target = 304 + byte
                        }
                        lda sourceBase + offset + source,x
                        sta targetBase + offset + target,x
                    }
                }
                rts
            }
        }
    }
}
copyRoutineLow:
    .fill 36, <copyAddresses.get(i)
copyRoutineHigh:
    .fill 36, >copyAddresses.get(i)
.assert "Loadable PRG stays below phase B destination", * <= $c000, true
.label bitmapB = BITMAP_B
.label screenB = SCREEN_B
.label actorAtlasB = ACTOR_B
