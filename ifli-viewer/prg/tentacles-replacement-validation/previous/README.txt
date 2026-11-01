STANDALONE PAL C64 IFLI IMAGES

face.prg
face2.prg
mage.prg
dragon.prg
abyss.prg
tentacles.prg
Surrealisk.prg
teapot.prg
Gladjefull (2).prg

Each PRG includes its image data and PAL display routine. Autostart it in
VICE configured for PAL. No separate FP2 file, viewer, disk image, or REU
is required. Each file is 48,013 bytes. Reset the emulator to leave an image.

Example command:
x64sc -pal -autostartprgmode 1 -autostart teapot.prg

The original six programs were tested by direct PRG autostart in PAL VICE 3.10.
Screenshots were inspected and every relocated phase-B byte matched the
source FP2 image. Original image data and FLI left-edge behavior are retained.

Surrealisk.prg also passed direct PAL VICE 3.10 autostart. Its embedded
image data was verified byte-for-byte against the source FP2 file.

Teapot passed direct PAL VICE 3.10 PRG autostart. Its visible image was
inspected, its display loop reached $2088, and all 16,292 relocated phase-B
bytes matched the source FP2. Its embedded FP2 payload also matched exactly.

Gladjefull (2).prg passed direct PAL VICE 3.10 PRG autostart. Its visible
image was inspected, its display loop reached $2088, and all 16,292 relocated
phase-B bytes matched the FP2. Its embedded FP2 payload also matched exactly.

Display routines: GoDot English PAL IFLI viewer, based on Fun Painter II.
https://www.godot64.de/iflis/diashow_eng.prg
https://github.com/godot64/GoDot/blob/master/extras/iflidiashow.a

build-receipt.json records input/output hashes and player provenance.
