// Complete original native SID driver and score data; no byte patches.
.const MUSIC_LOAD = $41c0
.const MUSIC_BYTES = 7709
.const MUSIC_INIT = $41c3
.const MUSIC_SELECT = $41c9
.const MUSIC_PLAY = $41c0
.const MUSIC_LEVEL1_CUE = 1
.const MUSIC_SOURCE_SUBTUNE = 3
.const MUSIC_ZERO_PAGE_FIRST = $a4
.const MUSIC_ZERO_PAGE_LAST = $b9
.var originalGameMusicFile = LoadBinary("music-original.bin")
musicOriginal:
    .fill originalGameMusicFile.getSize(), originalGameMusicFile.get(i)
musicOriginalEnd:
.assert "Music remains at its original address", musicOriginal, MUSIC_LOAD
.assert "Complete original music module", musicOriginalEnd - musicOriginal, MUSIC_BYTES
