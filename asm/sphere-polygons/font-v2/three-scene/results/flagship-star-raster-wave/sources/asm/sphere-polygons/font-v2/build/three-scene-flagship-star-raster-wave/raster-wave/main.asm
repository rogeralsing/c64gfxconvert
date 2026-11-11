.const PREVIEW_FRAME_COUNT = 97
.const RASTER_SPLIT_COUNT = 25
.var waveAgeData = LoadBinary("wave-ages.bin")
.var rasterRowData = LoadBinary("raster-rows.bin")
.var fontData = LoadBinary("font.bin")
.var movieData = LoadBinary("movie.bin")
.var pointerData = LoadBinary("pointers.bin")
.var scriptData = LoadBinary("playback.bin")
.import source "../../../raster-wave-player.asm"
