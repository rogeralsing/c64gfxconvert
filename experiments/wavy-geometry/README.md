# Three C64 scroll geometries

- `spiral.js` projects a wide diagonal corkscrew with curved ends. The tape scrolls from lower right to upper left. Black pixels cut between the two faces. The rear face mirrors the texture and alternates it with background pixels in a checkerboard.
- `disc.js` maps the tape around a perspective LP with a tilted plane and a center hole.
- `tunnel.js` maps 24 depth columns along the inside wall of a perspective tunnel. The wider far opening and logarithmic spacing keep the inner rings apart as the colors travel toward the viewer.

All three use the same 16-row color tape and advance half a column per update. The spiral updates every four PAL fields. The disc and tunnel update every three. The build uses the wave scroller's existing fitter, raster packer and player.

```sh
node experiments/wavy-geometry/build.cjs /tmp/wavy-geometry
python3 experiments/wavy-scroll-shapes/verify-four-line-scroll-vice.py /tmp/wavy-geometry/tunnel --fields 120 --start-offset 932
```

Open the generated `index.html` to compare the source geometry with the fitted C64 planes and download the three PRGs. Use the color grid to inspect the shape or switch to the demo color tape. Pass `spiral`, `disc` or `tunnel` after the output directory to rebuild a single PRG.
