# Four-line FLI scroller

The PAL demo in `demo/wave-four-line-scroll.prg` advances 1.5 wave columns every three PAL fields (16.71 updates/s).

Rebuild it from this directory with Node.js and Kick Assembler. The VICE check also needs `x64sc` and Python with Pillow.

```sh
bash build-four-line-scroll.sh /tmp/wavy-fli-scroll 64 16 ribbon checker demo/font-scroll-colors.bin 1.5 3
python3 verify-four-line-scroll-vice.py /tmp/wavy-fli-scroll --fields 18 --start-offset 932
```

The final build argument sets the number of PAL fields per update. It defaults to four for custom builds.
