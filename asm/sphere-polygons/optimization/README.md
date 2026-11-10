# Polygon delta and cache experiments

Five assembled 6502 kernels were compared with the frozen full renderer. Three subagents implemented the alternatives independently. The inter-frame delta versions were byte-exact but slower. Reusing shared edges within the same football frame gave a small CPU saving and crossed a PAL presentation threshold in the sampled native animation.

## Comparison

The table measures **raster CPU cycles**, including every new edge calculation, cache lookup, union/count operation, history update and fill. It excludes the common projection, font resolution, VIC bus stalls and presentation wait. Each column uses the same 32 animation poses. Positive changes mean more CPU work.

| Strategy | Checker animation | Football animation |
| --- | ---: | ---: |
| Retained merged spans; update changed probes | +90.84% | +53.00% |
| Retained spans; rebuild dirty character rows | +75.99% | +51.44% |
| Per-face span deltas with contribution counts | +55.19% | +44.45% |
| Normalized edge-curve cache across frames | +8.96% | +1.78% |
| Shared-edge cache within one frame | +0.19% | **−3.35%** |

All five passed 112 mixed cases: 32 animation frames per model, independent-axis motion, large jumps, pauses and model switches. Every case compared 1,000 coverage bytes and 1,000 post-clipping screen codes with the frozen full-render reference. The font and static assets were checked for mutation. Retained state lives through the entire sequence and starts from poisoned RAM; initialization runs once and is reported separately.

The shared-edge candidate also passed **560 cases**, including 256 consecutive animation poses per model and generation-tag wraparound. Over that complete rotation cycle, football raster CPU falls **3.11%** and checker raster CPU rises **0.19%**. Including font resolution, the changes are −2.71% and +0.09% respectively. These remain CPU replay results, not complete native frame times.

Detailed comparison receipts are archived in [results](results/). Full per-case output and generated PRGs remain under each variant's ignored `build/` directory. Sources, generated static topology and reproduction tools are retained.

## PAL VICE result

The shared-edge candidate passed the complete native verifier at normal PAL speed with warp off: **46 frames and 18 actual VIC screenshots**, both meshes and all three axes. Screen RAM, coverage, projected vertices, matrix coefficients, full mesh traversal and the unchanged font matched. Every lit glyph dot stayed inside the ball's circle.

| Model | Baseline mean render clocks | Shared-edge mean render clocks | Baseline median FPS | Shared-edge median FPS |
| --- | ---: | ---: | ---: | ---: |
| Checker | 236,490 | 236,712 | 3.856 | 3.856 |
| Football | 197,243 | 192,265 | 4.557 | **5.012** |

These are the same 16 sampled animation poses per model. The football saving brings all sampled presentations into ten PAL fields; most baseline intervals needed eleven. Median FPS therefore changes more than CPU work. The native sample does not establish the same cadence for every possible orientation. The 560-case replay covers the complete animation period for output correctness.

The accepted experimental PRG is `shared-edge-cache/build/variant.prg`. Build and open it with:

```sh
./optimization/shared-edge-cache/run.sh
```

F1 selects football / checker, F3 selects rotation axes and Space pauses. The original parent renderer remains the reproducible benchmark reference; the faster football candidate is a separate runnable variant.

## Why delta lost here

Clearing coverage and writing its changed bits are cheap compared with producing and maintaining interval descriptions. Sorted unions, endpoint sweeps and contribution counters added more work than they removed.

Dirty-row reuse was especially coarse: only 1.72 checker rows and 2.25 football rows out of 25 stayed unchanged on average. Many unchanged cells share a row with at least one moving edge.

The normalized cache had too few exact keys in the rotating sequence, so its miss and bookkeeping costs outweighed the saved DDA work. The smaller successful cache needs no geometric key search: static topology identifies 30 edges shared by white hexagons. The first face computes a live edge; the second reuses it within that frame. Generation tags prevent reuse from another pose.

These measurements reject the tested implementations, not all possible delta algorithms. No precomputed animation frames, host-generated spans, vertex-Z rejection or face-count cap supplied a timing advantage. All vertices still pass through the same native projection. Back-facing faces are culled by their normals, as in the reference.

## Reproduce

Requirements: Node.js, Python 3, KickAssembler, `rtk`, and py65 1.2.0. Native verification additionally needs VICE 3.10 and Pillow. Tool paths in the local scripts match the workstation used for the experiment.

From `asm/sphere-polygons`:

```sh
./build.sh
python3 -m venv optimization/build/venv
optimization/build/venv/bin/pip install -r optimization/requirements.txt
python3 optimization/common/build_variant.py optimization/shared-edge-cache
optimization/build/venv/bin/python optimization/common/benchmark.py --variant optimization/shared-edge-cache --frames 256
python3 verify-c64.py --program optimization/shared-edge-cache/build/variant.prg --symbols optimization/shared-edge-cache/build/main.sym --output build/verification-shared-edge --frames 16
```

Replace the strategy directory and use `--frames 32` to reproduce the comparison table. The common harness constructs every pose with native `select_model`, `prepare_matrix` and `project_vertices` before entering the timed raster. It verifies projected inputs too. Nothing supplies prebuilt spans or treats new edge calculations as free. The reference raster-plus-resolution cost at pose `(0,24,0)` is exactly 200,711 CPU cycles in both replay and the earlier VICE per-instruction profile.

The frozen baseline PRG SHA256 is `1379a1c305d1ef6553aead15fd74da1f093538cb88a0c4d57b5c71f7bb34b25c`. The shared-edge PRG SHA256 is `80c328509a5e5e5f127c67dcbe9e6f9efdfc30986fc5d12c9cecd92cbdb5be98`.
