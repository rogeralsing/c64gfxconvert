# Polygon-to-character experiment

Both models are computed on the 6510: checker sphere (62 vertices, 72 faces) and truncated icosahedron (60 vertices, 20 hexagons + 12 pentagons). All model faces are retained. Only white front-facing faces need painting on the black screen; no eight-face cap is allowed.

## Coordinates and projection

The renderer works in 40×25 character coordinates. Projected coordinates are Q3 characters: one unit is 1/8 of a character. Center is (20,12.5) characters, radius11.75 characters, represented as (160,100),radius94 in Q3. These integers retain precision for font selection; the renderer does not iterate through a 320×200 bitmap.

Glyph dot/sample coordinates use integer Q3 positions, without adding0.5. For a tile starting at Q3(x,y), the sample locations are x+[1,4,6],y+[1,4,6]. Independent visual references use the same integer dot-center convention. The static circle constraint also tests integer dot centers.

Projection is orthographic. Yaw, pitch and roll can change independently during execution. Roll rotates the camera-space X/Y rows; the depth row is unchanged. A face is front-facing when its rotated outward normal depth is negative, matching the existing sprite-ball convention. Static vertex and normal coordinates are signed Q6 values, with normalized unit radius64. Specialized product pages return signed bytes: coordinate × coefficient ×94/4096, using the geometry module's documented rounding. Projected X/Y are bytes; saturation prevents wraparound when quantization pushes a coordinate beyond255. The exact radius94 safety mask then clips the selected glyphs.

## Shared JavaScript API

`meshes.cjs`: exports checker,football,meshes,getMesh. Meshes contain float vertices,verticesQ6,faces; each face has indices,color,kind,normal,normalQ6. Colors are0/1. Checker colors alternate. Football hexagons are white and pentagons black.

`geometry.cjs`: exports matrix,product,productPages,project,projectFloat. `project(meshOrName,yaw,pitch,roll=0)` returns projectedX/projectedY Uint8Array(64),faceDepths,visible,faces with points and visibility. Its integer arithmetic must match geometry.asm.

`raster.cjs`: exports buildTables(font,{bits}), rasterize(projectedX,projectedY,faces,{bits,frontFaces,...}). Primary native mode uses8 probes: the3×3 grid omits its center. A9-probe host variant provides a quality comparison. Return coverage,screen,ops. White polygons merge coverage with OR before glyph selection.

## Raster strategy

There are75 sample lines, three per character row, at Q3 y=8*row+[1,4,6]. For each convex white front face:

1. Find its sample-line bounding range and clear only that portion of left/right crossing arrays.
2. Walk nonhorizontal edges in increasing Y, with half-open active interval[minY,maxY). Rational DDA gives ceil(X) at each sample line. quotient=floor(abs(dx)/dy),remainder=abs(dx)%dy. Consecutive Y sample gaps are3,2,3. No pixel-by-pixel edge walk is used.
3. Each line's span is[left,right). Determine partial endpoint masks and fill interior characters with full sample-row masks.
4. OR samples into one coverage byte per character: top row bits0,1,2; middle left/right bits3,4; bottom bits5,6,7. The unused middle-center sample contributes no bit.

After all faces, a256-byte fixed-font lookup converts each coverage byte to one character. Full and empty coverage must select full and empty glyphs. Cells shared by faces are resolved only once. A circle-safe remap of boundary glyphs prevents protrusions outside the mathematical ball. This remap is derived only from the static circle and font.

## Native ABI

Root main.asm owns global model,angle_yaw,angle_pitch,angle_roll,rotation_mode,paused,frame_counter,front_screen_hi,back_screen_hi. F3 cycles rotation_mode:0all axes,1yaw,2pitch,3roll.

Fixed RAM:

- $0400..$07ff and$0c00..$0fff: screen buffers.
- $1000..$13ff: coverage[1024].
- $1400..$143f: projected_x[64].
- $1440..$147f: projected_y[64].
- $1480..$14ca: span_left[75].
- $1500..$154a: span_right[75].
- $2000..$27ff: fixed256-glyph font.
- $3000..$3fff: main+geometry+raster code, guarded before assets.
- $4000 upwards: static geometry, product pages, arithmetic tables and font lookup data; stay below I/O unless explicitly revised.

Zero page $02..$7f belongs to raster; $80..$9f belongs to geometry. Root main uses$a0..$af. Raster defines face_ptr=$04 (two bytes) for its current12-byte face record. It remains valid across face_front calls.

Geometry globals: vertex_count,face_count are bytes in code RAM. vertices_base and faces_base are geometry-owned zero-page pointers. `select_model`: A=model0checker/1football, initialize pointers/counts. `prepare_matrix`: reads global angle_yaw/angle_pitch/angle_roll. `project_vertices`: fills fixed projected arrays using selected model. `face_front`: reads normal product-page bytes from face_ptr offsets2..4, returns A=1(front) or0(back), other scratch registers may change; sets normal_depth for inspection.

Assets use labels checker_vertices,checker_faces,football_vertices,football_faces. Each vertex record has three absolute product-page high bytes for X/Y/Z. Each face record is12bytes: count,color,normalXPage,normalYPage,normalZPage,vertex0..vertex5,padding. Unused vertex indices are0. Product pages are page-aligned, indexed by signed Q6 coefficient byte. `sin_table` is256 signed Q6 bytes.

Raster exports `render_polygons` (clear coverage, iterate selected faces, fill coverage) and `resolve_screen` (map coverage to hidden screen and apply safe boundary remaps). It reads geometry's face_count/faces_base and calls face_front. It must not alter global angles. Screen resolution may patch only its own store high bytes for$0400/$0c00.

Root exports render_start,render_end,frame_done,geometry_start,geometry_end,raster_start,raster_end,resolve_start,resolve_end. frame_done occurs after the complete hidden screen is presented at PAL raster wrap and before angles advance. F1 selects model; F3 selects rotation axes; space pauses. No prepared animation frames, screen deltas or runtime high-resolution reference image are allowed.

## Verification

The native model combines integer geometry and span rasterization, returning1000screen bytes. Independent reference code uses projected polygon point-inclusion, not the span algorithm. Compare both models across varied yaw/pitch/roll, actual native screen RAM and the fixed font. Check the mathematical circle for every lit glyph dot, face completeness, backface selection, stable font, and correct composition at shared character cells. Measure geometry/raster/resolve cycle regions separately in PAL VICE at normal speed.

The static outer clipping radius is101 Q3 units. The coefficient certificate checks all256³ quantized rotation matrices and bounds every projected mesh vertex, including product rounding, below100.228. Polygon spans stay inside that bound. Empty coverage selects the empty glyph, so tiles beyond the bound cannot acquire a glyph from the sparse lookup. Every glyph dot in an affected tile must remain inside the final radius94 circle.
