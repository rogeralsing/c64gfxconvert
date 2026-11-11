.var movieData=LoadBinary("rows.bin")
.var indexData=LoadBinary("frame-offsets16.bin")
.var waveData=LoadBinary("wave-ages.bin")
.var fontData=LoadBinary("font.bin")
.var hData=LoadBinary("h-lut.bin")
.var vData=LoadBinary("v-lut.bin")
.var zoomData=LoadBinary("learned.lut")
.import source "sources/asm/sphere-polygons/font-v2/span-zoom-player.asm"
