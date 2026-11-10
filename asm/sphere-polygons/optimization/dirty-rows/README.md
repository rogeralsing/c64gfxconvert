# Dirty character-row cache experiment

This is a rejected native 6502 prototype. The frozen parent renderer is unchanged. The prototype preserves exact coverage and screen codes on the replay sequence, but uses more CPU time.

## Strategy

Every frame still performs native culling and edge DDA. Instead of immediately painting every polygon span, it records exact quantized intervals at the 75 character sample lines. Top and bottom sample lines use three probe positions per character; middle lines use two. Sorting and merging produce a canonical union of intervals independent of face order and overlaps.

Each character row owns three sample lines. The prototype compares their complete interval descriptors with retained history. An unchanged row keeps its existing coverage bytes. A changed row clears its 40 coverage bytes and replays every new interval for the three sample lines. Rebuilding from zero handles removal of old white areas correctly. There are no hashes or collision-prone summaries.

The interval capacity is 36 per sample line, matching the complete checker's 36 white faces. Each white face contributes at most one interval to a sample line. The football has only 20 white faces. No face cap or host-generated span input is used. Model switches compare the new unions against the existing history without special host resets.

`resolve_screen` remains the frozen implementation, including the fixed 256-character font and circle-safe remapping. The coverage buffer is retained between successive frames; both destination screen buffers are still fully resolved.

## Reproduce

Run from `asm/sphere-polygons`:

```sh
python3 optimization/common/build_variant.py optimization/dirty-rows
PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 optimization/common/benchmark.py --variant optimization/dirty-rows --frames 32
```

The replay requires py65. The temporary `PYTHONPATH` above identifies the environment used for this measurement; an installed py65 package also works.

## Measured result

The 112-frame sequence includes 32 animation frames per model, independent-axis motion, large orientation jumps, pauses and model switches. One initialization runs before the entire sequence. All 112,000 coverage bytes and 112,000 resolved screen bytes match the frozen host model. Font and static assets remain unchanged.

| Group | Baseline raster CPU cycles | Prototype raster CPU cycles | Change | Raster plus resolution change |
| --- | ---: | ---: | ---: | ---: |
| Checker animation, 32 frames | 176,829.31 | 311,198.31 | +75.99% | +66.00% |
| Football animation, 32 frames | 147,232.13 | 222,966.25 | +51.44% | +43.58% |
| Complete mixed sequence, 112 frames | 159,415.50 | 260,905.71 | +63.66% | +54.57% |

These are assembled NMOS 6502 instruction cycles. They exclude geometry, VIC bus stalls, IRQs and presentation waiting. They are not native FPS measurements. Initialization costs another 1,002 CPU cycles once. Resolution is unchanged and has identical cycle counts for each matching frame.

The receipt is `build/benchmark.json`. The candidate PRG SHA256 is `85e61dff1e5634fbfb1879ec2768aecf756a5f18043d992051348b19a2b25f70`.

A separate diagnostic replay reads the existing native dirty flags only after the timed renderer returns. It adds no instruction or source instrumentation. In the same 32-frame animation groups:

| Model | Mean dirty rows, out of 25 | Mean unchanged rows | Unchanged fraction |
| --- | ---: | ---: | ---: |
| Checker | 23.28125 | 1.71875 | 6.875% |
| Football | 22.75 | 2.25 | 9.00% |

That diagnostic also verifies coverage and screen bytes. Its receipt is `build/dirty-row-counts.json`. Canonical interval counts average 243.75 per checker frame and 122.5 per football frame. Too few complete rows remain unchanged to repay sorting, union construction, comparisons and history maintenance in this implementation.

## Code and memory

The helper code and descriptor tables occupy `$1600..$1cdc`: 1,757 bytes in unused low RAM. The modified main code region is 15 bytes smaller than the parent. The PRG still ends below I/O because high retained buffers are address labels, not emitted load data.

Retained state occupies 10,975 bytes:

- Current interval buffers: 5,400 bytes, split between `$c000..$cfbf` and `$f600..$fb57`.
- Previous interval buffers: 5,400 bytes at `$e000..$f517`.
- Current counts: 75 bytes at `$fb60..$fbaa`.
- Previous counts: 75 bytes at `$fbb0..$fbfa`.
- Dirty flags: 25 bytes at `$fc00..$fc18`.

The prototype also uses 21 scratch zero-page bytes at `$40..$54`. Its range assertions protect I/O, hardware vectors, the fixed font and static parent data. `delta_init` invalidates every historical count and initializes the unused coverage tail; it does not assume zero-filled power-on RAM.
