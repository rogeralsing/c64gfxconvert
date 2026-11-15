# Giana7 second room

`giana7.koa` is an exact copy of the user-supplied `images/giana7.koa`.
Its SHA-256 is
`7381892c788b6e47c7d0f17eda8b19bf5ca7eaab29e684aa8fe41dcaa15c1ce5`.
The original Koala load address is `$6000`; the demo does not use that address
as an instruction to overwrite its renderer. The image has 8,000 bitmap bytes,
1,000 screen bytes, 1,000 color bytes and global background 9.

The companion `images/giana7.json` has SHA-256
`ea117837566896e8f3f9b67e04bc76e4319e5a12e9029ce28ae5a4e73e91d06b`.
Its `ScreenLight` marker contains 121 cells. Its 80-cell `GameArea` matches
the first room's ten-column, eight-row rectangle at character column23, row3.
The masks do not overlap. Both editor layers are hidden; the user's explicit
instruction makes them active runtime masks. The game replaces the exported
white TV area, and the marked room cells receive the same protected-color
illumination as the first scene. Other source pixels remain unchanged.

Rebuild offline from the retained source files with:

```sh
python3 giana/tools/prepare-ending.py
```

`ending-packbits.bin` first stores the unchanged 8,000 bitmap bytes and
1,000 screen bytes. The 1,000 Color RAM bytes all have zero high nibbles, so
two indices fit losslessly into each of 500 bytes: even cell in the high nibble,
odd cell in the low nibble. The background is the separate `ENDING_BACKGROUND`
assembly constant. Those 9,500 bytes compress to a 7,995-byte stream at
`$E000..$FF3A`, beneath the KERNAL ROM and below the hardware vectors.
`ending.asm` imports the stream at its caller's chosen PC and exports
`endingPacked`, `endingPackedEnd` and `ENDING_PACKED_BYTES`.
`ENDING_UNPACKED_BYTES` is 9,500 and `ENDING_COLOR_PACKED_BYTES` is 500.

Each packet has its tag at the end so native code can decode backward:

- A literal packet is 1–128 unchanged bytes followed by a tag 0–127.
- A repeat packet is one value followed by a tag 128–255; repeats start at
  three equal bytes.
- The count is `(tag & 127) + 1` for either packet type.

Read a tag from the end, then consume the preceding literal bytes or value.
Write output from its end toward its start. For each decoded color pair,
write the odd cell's low nibble first, then the even cell's high nibble.
The source is not a normal Koala
file and must be relocated safely before use; ordinary PRG loading must not
write through the live I/O window.

The importer round-trips every packed byte against the exact source and
records component hashes, marker masks and preservation details in
`ending-import.json`. Its packed SHA-256 is
`d0675e6ad6b6bdde9833baea7e6131bad28816827df18b11aab686a0a65d1eaa`.
Pillow optionally writes `ending-preview.png`; it does not affect the native
payload. The original image and project files remain unchanged.

## Second-room illumination

`scene7-lighting.bin` has 968 bytes: 121 low screen addresses, 121 high screen
addresses, three phase-major screen-color tables and three phase-major Color
RAM tables. Each table has one byte per marked cell. Screen addresses target
`$0400+cell`; adding `$D4` to an address's high byte targets Color RAM.

`scene7-lighting.asm` exports `SCENE7_LIGHT_TILE_COUNT`, the cell address
tables, and `scene7LightScreen0/1/2` and `scene7LightColor0/1/2`. Its data fits
at `$8C00..$8FC7`. All palette rules come directly from `prepare-scene.py`:
black0, white1, red2, dark blue6, brown9 and dark gray11 remain fixed.
`scene7-lighting.json` records the source cells, phase layout and table hash.
