// Original Giana intro art, reduced by tools/prepare-intro.py.
// CPU source atlas; import at the caller's 64-byte-aligned address.
.const INTRO_SMALL_WALK_0 = 0
.const INTRO_SMALL_WALK_1 = 2
.const INTRO_SMALL_JUMP = 4
.const INTRO_ELECTRIC = 6
.const INTRO_BALL_0 = 8
.const INTRO_BALL_1 = 9
.const INTRO_SMALL_HEIGHT = 8
.const INTRO_ELECTRIC_HEIGHT = 10
.const INTRO_BALL_HEIGHT = 6
.const INTRO_WIDTH_MC = 6
.const INTRO_PLANE_COUNT = 10
.const INTRO_SPRITE_BYTES = 640
.var INTRO_PLANE_COLORS = List().add(7,6,7,6,7,6,7,1,7,7)
.var INTRO_PLANE_HEIGHTS = List().add(8,8,8,8,8,8,10,10,6,6)
.var introSpriteFile = LoadBinary("intro-sprites.bin")
introSpriteFrames:
    .fill introSpriteFile.getSize(), introSpriteFile.get(i)
introSpriteFramesEnd:
.assert "Ten 64-byte intro planes", introSpriteFramesEnd - introSpriteFrames, INTRO_SPRITE_BYTES
.assert "Intro atlas is 64-byte aligned", introSpriteFrames & $3f, 0
