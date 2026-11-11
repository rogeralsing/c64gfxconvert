.const PREVIEW_FRAME_COUNT = 106
.const LOOP_START_FRAME = 10
.const MOVIE_POOLED = false
.const MOVIE_MIDDLE_START = 5888
.const LITERAL_CODEC = true
.var fontData = LoadBinary("font.bin")
.var movieData = LoadBinary("movie.bin")
.var movieLowData = movieData
.var movieMiddleData = movieData
.var movieUpperData = movieData
.var pointerData = LoadBinary("pointers.bin")
.var scriptData = LoadBinary("playback.bin")
.import source "../../../../../scene-player.asm"
