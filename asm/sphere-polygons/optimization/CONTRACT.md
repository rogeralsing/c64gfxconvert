# Native delta experiment ABI

The parent renderer and its assets are the frozen reference. Each strategy owns only its named directory. Shared build and replay tools live in `common/` and belong to the coordinator.

Provide `raster.asm` in the strategy directory, based on the parent file. Preserve the exported `render_polygons` and `resolve_screen` entries. An optional `extra.asm` is appended after the parent's static assets. This allows extra helper code or state outside the original code region while retaining the parent's code/data guards. Add explicit range guards for your extra allocations. An optional `delta_init` entry is called once before the complete replay sequence.

`common/build_variant.py STRATEGY_DIRECTORY` copies the frozen main, geometry and assets into an ignored build directory, substitutes your raster, appends optional extra code, and assembles `build/variant.prg` plus `build/main.sym` and `build/variant.dbg`.

The timed entry is `render_polygons`. Its inputs are the selected model, the normal projection matrix, and projected vertex arrays in the parent ABI. New edge construction, culling, union construction, comparisons, history updates, clearing and coverage updates must all execute inside this entry. Host-generated spans, masks and animation deltas are forbidden. Shared geometry is excluded from the raster comparison because all strategies use the same projected inputs. A successful candidate is then checked as a complete live C64 program.

The benchmark supplies live geometry using the parent's native select_model/prepare_matrix/project_vertices routines. It compares all 1,000 coverage bytes and all 1,000 post-clipping screen bytes with the frozen host model. `resolve_screen` remains callable and is measured separately. Back-screen addresses alternate $0400/$0c00, so a strategy changing resolution must honor the actual target buffer. The sequence includes both meshes, three-axis motion, pauses, large orientation jumps and model switches. State persists for the entire sequence; delta_init is not called on model switches.

RAM $c000..$cfff and $e000..$fff9 is available for private helpers/state, in addition to unused low RAM. Do not touch I/O $d000..$dfff, vectors $fffa..$ffff, font $2000..$27ff, screen buffers, or parent static data $4000..$bfaf. Geometry owns ZP $80..$9f; raster may use $02..$7f. Maintain the parent coverage/projection/span addresses. Startup must initialize all retained state explicitly; do not depend on power-on RAM.

Benchmark CPU cycles come from assembled NMOS 6502 instructions in py65. They exclude VIC bus stalls, IRQs and presentation waiting. Report those limits; do not present replay cycles as native FPS. A winning integrated build must pass PAL VICE against the same char output.
