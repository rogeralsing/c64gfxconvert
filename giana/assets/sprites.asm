// Original C64 Giana and Stage 1 owl, reduced by tools/prepare-sprites.py.
// Import at a VIC-visible address aligned to 64 bytes. Code 0 is transparent.
.const SPRITE_MC0 = 10
.const SPRITE_MC1 = 2
.const SPRITE_GIANA_COLOR = 7
.const SPRITE_ENEMY_COLOR = 1
.const SPRITE_GIANA_LAYER1_COLOR = 6
.const SPRITE_GIANA_FRAME_COUNT = 4
.const SPRITE_ENEMY_FRAME_COUNT = 2
.const SPRITE_GIANA_PLANES = 2
.const SPRITE_ENEMY_PLANES = 1
.const SPRITE_GIANA_STRIDE = 2
.const SPRITE_ENEMY_STRIDE = 1
.const SPRITE_GIANA_FRAME_OFFSET = 0
.const SPRITE_ENEMY_FRAME_OFFSET = 8
.const SPRITE_FRAME_COUNT = 10
.const SPRITE_FRAME_BYTES = 64
.const SPRITE_PLAYER_X_MC = 10
.const SPRITE_PLAYER_WIDTH_MC = 6
.const SPRITE_GIANA_WIDTH = 12
.const SPRITE_GIANA_HEIGHT = 10
.const SPRITE_ENEMY_WIDTH = 12
.const SPRITE_ENEMY_HEIGHT = 9
.var originalTinySpriteFile = LoadBinary("sprites.bin")
tinySpriteFrames:
    .fill originalTinySpriteFile.getSize(), originalTinySpriteFile.get(i)
tinySpriteFramesEnd:
.assert "Ten 64-byte tiny sprite planes", tinySpriteFramesEnd - tinySpriteFrames, SPRITE_FRAME_COUNT * SPRITE_FRAME_BYTES
.assert "Tiny sprite atlas is 64-byte aligned", <tinySpriteFrames & $3f, 0
