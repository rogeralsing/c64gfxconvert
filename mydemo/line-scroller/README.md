# Line Scroller

Large uppercase letters scroll from right to left on a 160×100 logical grid.
Each letter is a set of connected points and straight strokes. A, B, and C use
three, five, and four strokes respectively. The build splits strokes at
existing junctions so connected lines share the same deformed vertex.

Every picture, the 6510 applies two travelling sine offsets per axis to each
vertex. The phases depend on the vertex's position, so the letters deform
along the same wave. Megaplot's line renderer stamps its existing font and
merges overlapping cells. Strokes are clipped at both screen edges.

```sh
python3 mydemo/line-scroller/build_scroller.py
x64sc -pal -autostart mydemo/line-scroller/build/line-scroller.prg
```

Supply your own message with `--text "NOICE  TWIST AND BEND"`. The alphabet
supports A–Z and spaces.

The scroller advances one logical pixel per picture. The deformation clock
advances every second picture.

Run `python3 mydemo/line-scroller/verify_scroller.py` to check a complete
message cycle and the PAL border flips.
