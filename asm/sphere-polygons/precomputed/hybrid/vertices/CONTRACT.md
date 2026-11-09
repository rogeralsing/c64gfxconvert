# Projected-geometry movie benchmark

PV64 v1 stores the existing 64-frame checker symmetry loop as all 62 projected XY vertices, shared topology for the 36 white faces, and precomputed visibility. Black areas begin empty. No vertex is rejected by its Z coordinate. The native player performs no matrix projection or normal-based culling.

The 12-byte header is `PV64`, version1, delta mode1, vertex count62, face count36, frame countLE16=64, bits per vertex delta4, codebook count15. Each topology record is a count/color byte (count in bits0–6, white in bit7) followed by byte vertex indices. The 168-byte topology begins at offset12. Fifteen signed `(dx,dy)` byte pairs follow at offset180.

The first frame begins at offset210: 124 interleaved absolute XY bytes, then five visibility bytes. All later frames contain 31 bytes of packed vertex-vector codes, then five visibility bytes. The low nibble addresses the earlier vertex; visibility bits use LSB-first face order. Unused high bits of the fifth visibility byte are zero. The complete movie is 2,607 bytes. Looping restores the first absolute vertex frame, because geometric vertex identities are permuted by the pattern's 60° symmetry.

`generate.cjs` copies only the raster/font tables required by the exact reference renderer. It renders decoded geometry against the existing 64 character images and saves separate XY, coverage and character references. References are verifier input and must never be loaded by a native player.

Native renderers use the same fixed font at `$2000` and alternating screens `$0400/$0c00`. The required playback checkpoints are `render_start`, `render_end`, `frame_done`, `frame_index`, `frame_counter`, `front_screen_hi` and `back_screen_hi`. At `frame_done`, the index identifies the image just presented. The immutable imported movie uses `animation` and `animation_end` labels.

Timing checkpoints are `decode_start/end`, `clear_start/end`, `face_edges_start/end`, `face_fill_start/end` and `resolve_start/end`. `raster_vertex_count` identifies three- versus four-vertex faces at per-face checkpoints; `current_face_index` identifies the shared topology record. Adjacent checkpoint labels must occupy different program addresses so each interval is measurable. Raster clocks include VIC bus stalls; complete playback cadence also includes presentation waiting. There is no fixed FPS cap.
