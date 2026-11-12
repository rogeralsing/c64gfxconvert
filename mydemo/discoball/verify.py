#!/usr/bin/env python3
"""Check geometry bounds, then compare native PAL VICE sprites with polygon coverage."""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

from model import HEXAGON_CORNERS, coefficients, model, project

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("cube_verification", HERE / "vice_support.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def checkpoint(monitor, command):
    response = monitor.run(command)
    match = re.search(r"(?:BREAK|WATCH|TRACE): (\d+)", response)
    if not match:
        raise RuntimeError(f"VICE did not create a checkpoint: {response}")
    return int(match[1])


def zoom_scale(phase):
    if not 64 <= phase < 192:
        return 64
    return math.floor(58+6*math.cos(math.tau*(phase-64)/128)+0.5)


def scale_q6(value, scale):
    return ((value+scale)**2//256)-((value-scale)**2//256)


def motion_speed(phase, slow, fast):
    phase &= 255
    blend = 1 if 96 <= phase < 160 else 0
    if 64 <= phase < 96:
        blend = (1-math.cos(math.pi*(phase-64)/31))/2
    elif 160 <= phase < 192:
        blend = (1+math.cos(math.pi*(phase-160)/31))/2
    return math.floor(slow+(fast-slow)*blend+0.5)


def zoom_matrix(matrix, scale):
    if scale == 64:
        return matrix
    return tuple(scale_q6(value, scale) for value in matrix[:5])+tuple(matrix[5:])


def check_bounds(faces, golden, zoom=False):
    # All 65,536 yaw/pitch pairs, including poses not used by the animation.
    matrix = np.asarray([coefficients(yaw, pitch)
                         for yaw in range(256) for pitch in range(256)], dtype=np.int32)
    scales = range(52, 65) if zoom else (64,)
    if zoom:
        scaled_matrices = []
        for scale in scales:
            scaled = matrix.copy()
            if scale != 64:
                scaled[:, :5] = scale_q6(scaled[:, :5], scale)
            scaled_matrices.append(scaled)
        matrix = np.concatenate(scaled_matrices)
    mul = lambda a, b: ((a + b) ** 2 // 256) - ((a - b) ** 2 // 256)
    counts = np.zeros(len(matrix), dtype=np.int32)
    highlights = np.zeros(len(matrix), dtype=np.int32)
    face_depths = []
    maximum_width = maximum_height = 0
    maximum_edge_dx = maximum_edge_dy = 0
    maximum_error = 0
    for face in faces:
        p = np.asarray(face["vertices"], dtype=np.int32)
        x = 64 + mul(p[:, 0], matrix[:, 0, None]) + mul(p[:, 2], matrix[:, 1, None])
        y = (64 - mul(p[:, 0], matrix[:, 2, None]) - mul(p[:, 1], matrix[:, 3, None])
             - mul(p[:, 2], matrix[:, 4, None]))
        if "basis" in face:
            original_x, original_y = x, y
            exact = lambda a, b: np.sign(a*b)*((np.abs(a*b)+32)//64)
            x = 64+exact(p[:, 0], matrix[:, 0, None])+exact(p[:, 2], matrix[:, 1, None])
            y = (64-exact(p[:, 0], matrix[:, 2, None])-exact(p[:, 1], matrix[:, 3, None])
                 -exact(p[:, 2], matrix[:, 4, None]))
            maximum_error = max(maximum_error, int(np.max(np.abs(x-original_x))),
                                int(np.max(np.abs(y-original_y))))
        if golden:
            inverse_phi = (5 ** 0.5 - 1) / 2
            for coordinates in (x, y):
                original = coordinates.copy()
                rounded = lambda v: np.sign(v) * np.floor(np.abs(v) * inverse_phi + 0.5).astype(np.int32)
                coordinates[:, 1] = coordinates[:, 0] + rounded(coordinates[:, 2] - coordinates[:, 4])
                coordinates[:, 3] = coordinates[:, 4] + rounded(coordinates[:, 2] - coordinates[:, 0])
                maximum_error = max(maximum_error, int(np.max(np.abs(coordinates-original))))
        n = face["normal"]
        normal_mul = exact if "basis" in face else mul
        z = normal_mul(n[0], matrix[:, 5]) + normal_mul(n[1], matrix[:, 6]) + normal_mul(n[2], matrix[:, 7])
        face_depths.append(z)
        highlights += -z / sum(v*v for v in n)**0.5 >= 0.94
        counts += z < 0
        # Include hidden faces too, for a stronger size bound.
        maximum_width = max(maximum_width, int(np.max(np.ptp(x, axis=1))))
        maximum_height = max(maximum_height, int(np.max(np.ptp(y, axis=1))))
        maximum_edge_dx = max(maximum_edge_dx, int(np.max(np.abs(x-np.roll(x, 1, axis=1)))))
        maximum_edge_dy = max(maximum_edge_dy, int(np.max(np.abs(y-np.roll(y, 1, axis=1)))))
    maximum_visible = int(np.max(counts))
    shared_mesh = any("basis" in face for face in faces)
    pentagons = all(len(face["vertices"]) == 5 for face in faces)
    if shared_mesh and not pentagons:
        for _, neighbors in reference_gap_faces(faces):
            normal = [sum(faces[i]["normal"][axis] for i in neighbors) for axis in range(3)]
            facing = -sum(face_depths[i] for i in neighbors)
            highlights += facing / sum(v*v for v in normal)**0.5 >= 0.94
    assert highlights.max() <= 2, "Three faces lie within the near-front cone"
    capacity = 6 if shared_mesh and pentagons else (10 if shared_mesh else 8)
    if maximum_width >= 24 or maximum_height >= 21 or maximum_visible > capacity:
        raise AssertionError(f"Sprite capacity exceeded: {maximum_width=}, {maximum_height=}, visible={np.max(counts)}")
    if zoom:
        assert maximum_height <= 19 and maximum_edge_dx <= 9 and maximum_edge_dy <= 10, "Quantized zoom exceeds the compact edge tables or sprite fill rows"
    return {"angle_pairs": 65536, "maximum_face_span": [maximum_width, maximum_height],
            "angle_scale_pairs": len(matrix), "zoom_scales_checked": list(scales),
            "maximum_visible_faces": maximum_visible,
            "maximum_rendered_faces": min(8, maximum_visible),
            "maximum_nearly_front_faces": int(highlights.max()),
            "maximum_corner_difference_from_baseline": maximum_error,
            "maximum_edge_dx": maximum_edge_dx, "maximum_edge_dy": maximum_edge_dy}


def check_edge_curves(ram, labels):
    samples = 0
    for dy in range(-20, 21):
        for dx in range(1, labels["edgeMaxDX"]+1):
            offset = (dy+20)*24+dx
            address = ram[labels["hexEdgeLow"]+offset] | ram[labels["hexEdgeHigh"]+offset]<<8
            for n in range(dx):
                assert ram[address+n]-20 == -((-n*dy)//dx), (dx, dy, n)
                samples += 1
    return samples


def polygon_bytes(points):
    """Independent rational intersections; fill spans directly, without XOR."""
    data = bytearray(63)
    for x in range(24):
        crossings = []
        for p, q in zip(points, points[1:] + points[:1]):
            if p[0] > q[0]:
                p, q = q, p
            if p[0] <= x < q[0]:
                dx = q[0] - p[0]
                numerator = (q[1] - p[1]) * (x - p[0])
                crossings.append(p[1] - ((-numerator) // dx))
        if len(crossings) % 2:
            raise AssertionError("Polygon reference has an unpaired intersection")
        crossings.sort()
        for first, last in zip(crossings[::2], crossings[1::2]):
            for y in range(first, last):
                if not 0 <= y < 21:
                    raise AssertionError(f"Polygon left sprite bounds at {(x, y)}")
                data[y * 3 + x // 8] |= 0x80 >> (x & 7)
    return bytes(data)


def decode_bitmap(bitmap, screen, color_ram, background):
    packed = np.frombuffer(bitmap, dtype=np.uint8).reshape(25, 40, 8)
    rows = packed.transpose(0, 2, 1).reshape(200, 40)
    codes = ((rows[:, :, None] >> np.array([6, 4, 2, 0])) & 3).reshape(200, 160)
    attributes = np.frombuffer(screen, dtype=np.uint8).reshape(25, 40).repeat(8, axis=0).repeat(4, axis=1)
    local = np.frombuffer(color_ram, dtype=np.uint8).reshape(25, 40).repeat(8, axis=0).repeat(4, axis=1) & 15
    indices = np.choose(codes, [np.full_like(local, background), attributes >> 4, attributes & 15, local])
    return indices, codes


def opening_mask(indices, center):
    center_x, center_y = center
    opening = np.zeros(indices.shape, dtype=bool)
    pending = [(center_x//2, center_y)]
    while pending:
        x, y = pending.pop()
        if not (0 <= x < 160 and 0 <= y < 200) or opening[y, x] or indices[y, x] != 0:
            continue
        opening[y, x] = True
        pending.extend(((x-1, y), (x+1, y), (x, y-1), (x, y+1)))
    return opening


def check_scene(artwork, bitmap, screen, color_ram, scene, phase=0):
    calibration = json.loads((HERE / "assets" / "scene-circle-repair.json").read_text())
    assert hashlib.sha256(artwork).hexdigest() == calibration["source_sha256"]
    assert scene["center"] == calibration["center"]
    if scene["format"] == "truepaint_mci":
        assert len(artwork) == 19434 and artwork[:2] == bytes((0, 0x9c))
        original_bitmaps = (artwork[1026:9026], artwork[9218:17218])
        original_screens = (artwork[2:1002], artwork[17410:18410])
        original_colors = bytes(value & 15 for value in artwork[18434:19434])
        assert scene["background"] == artwork[1002]&15
    else:
        original_bitmaps = (artwork[2:8002],)*2
        original_screens = (artwork[8002:9002],)*2
        original_colors = bytes(value & 15 for value in artwork[9002:10002])
        assert scene["background"] == artwork[10002]&15
    original_bitmap, original_screen = original_bitmaps[phase], original_screens[phase]
    disco = scene.get("disco")
    if not disco:
        assert bitmap == original_bitmap, "Source bitmap changed, including sphere artwork"
        assert screen == original_screen, "Source screen colors changed"
        assert color_ram == original_colors, "Source Color RAM changed"
        assert scene["bitmap_passthrough"] is True
        return {"initial_pixel_differences": 0, "opening_pixels": 0}
    assert scene["bitmap_passthrough"] is False
    assert disco["selector"] == 3 and disco["phase_count"] == 16 and disco["tick_divider"] == 4
    assert len(disco["palette"]) == 16 and all(0 <= value < 16 for value in disco["palette"])
    cells = disco["cells"]
    assert cells and len(cells) == len(set(cells)) and all(0 <= cell < 1000 for cell in cells)
    # Derive the opening independently from the original decoded image, without
    # trusting the preparer's pixel mask or its selected-cell inventory.
    original_fields, openings, required_cells = [], [], set()
    for field_bitmap, field_screen in zip(original_bitmaps, original_screens):
        indices, _ = decode_bitmap(field_bitmap, field_screen, original_colors, scene["background"])
        opening = opening_mask(indices, scene["center"])
        original_fields.append(indices)
        openings.append(opening)
        required_cells.update(np.flatnonzero(opening.reshape(25, 8, 40, 4).any(axis=(1, 3))).tolist())
    assert set(cells) == required_cells, "Disco cells must cover every pixel of the complete circle opening"
    assert disco["coverage"] == "full_opening" and disco["white_contour_preserved"] is True
    prepared_colors = bytearray(original_colors)
    for cell in cells:
        prepared_colors[cell] = 0
    assert color_ram == bytes(prepared_colors), "Disco preparation changed Color RAM outside its selected cells"
    selected_cells = np.zeros(1000, dtype=bool)
    selected_cells[cells] = True
    original_bytes = np.frombuffer(original_bitmap, dtype=np.uint8).reshape(1000, 8)
    prepared_bytes = np.frombuffer(bitmap, dtype=np.uint8).reshape(1000, 8)
    assert np.array_equal(prepared_bytes[~selected_cells], original_bytes[~selected_cells]), "Disco preparation changed bitmap cells outside the opening"
    original_attributes = np.frombuffer(original_screen, dtype=np.uint8)
    prepared_attributes = np.frombuffer(screen, dtype=np.uint8)
    assert np.array_equal(prepared_attributes[~selected_cells], original_attributes[~selected_cells]), "Disco preparation changed screen attributes outside the opening"
    original, opening = original_fields[phase], openings[phase]
    prepared, prepared_codes = decode_bitmap(bitmap, screen, color_ram, scene["background"])
    selected = selected_cells.reshape(25, 40).repeat(8, axis=0).repeat(4, axis=1)
    assert np.all(prepared_codes[opening] == 3), "Every circle-opening pixel must use the shared disco selector"
    assert not np.any((prepared_codes == 3) & selected & ~opening), "Shared disco selector escaped the circle pixel mask"
    assert np.all(prepared[opening] == 0), "Disco preparation changed the initial black opening"
    outside = ~opening
    assert np.array_equal((prepared == 1)[outside], (original == 1)[outside]), "Disco preparation changed the white contour"
    assert np.all(prepared[outside & (original == 0)] == 0), "Disco preparation changed original black pixels outside the opening"
    recolored = int(np.count_nonzero((prepared != original) & outside))
    assert disco["edge_recolored_multicolor_pixels"][phase] == recolored, "Boundary repair multicolor count differs from decoded pixels"
    assert disco["edge_recolored_pixels"][phase] == recolored*2, "Boundary repair screen-pixel count differs from decoded pixels"
    for color in range(16):
        flashed_colors = bytearray(color_ram)
        for cell in cells:
            flashed_colors[cell] = color
        flashed, _ = decode_bitmap(bitmap, screen, flashed_colors, scene["background"])
        assert np.array_equal(flashed[outside], prepared[outside]), "Disco palette changes escaped the circle pixel mask"
        assert np.all(flashed[opening] == color), "Disco palette does not control the entire circle opening"
    return {"initial_pixel_differences": recolored*2, "opening_pixels": int(opening.sum())*2}



def render_preview(ram, labels, colors, color_ram, background, sprite_colors=None, phase=0, horizontal_shift=0):
    base = ram[labels["shownMetadataBase"]]
    screen = (0x400, 0x7c00)[phase]
    bitmap = (0x2000, 0x4000)[phase]
    indices, _ = decode_bitmap(ram[bitmap:bitmap+8000], ram[screen:screen+1000], color_ram, background)
    indices = indices.repeat(2, axis=1)
    if phase and horizontal_shift:
        indices = np.pad(indices, ((0, 0), (horizontal_shift, 0)), constant_values=background)[:, :320]
    image = Image.fromarray(np.asarray(colors, dtype=np.uint8)[indices])
    pixels = image.load()
    base = ram[labels["shownMetadataBase"]]
    buffer = (0x0c00, 0x7800)[phase] + (base // 8) * 512
    count = ram[labels["usedSprites"]]
    for slot in reversed(range(count)):
        x = ram[labels["slotX"] + base + slot] - 24
        y = ram[labels["slotY"] + base + slot] + 1 - 51
        color_index = ram[labels["slotColor"] + base + slot] if sprite_colors is None else sprite_colors[slot]
        color = colors[color_index]
        data = ram[buffer + slot * 64:buffer + slot * 64 + 63]
        for row in range(21):
            for column in range(24):
                if data[row * 3 + column // 8] & (0x80 >> (column & 7)):
                    for py in (y+2*row, y+2*row+1):
                        for px in (x+2*column, x+2*column+1):
                            if 0<=px<320 and 0<=py<200:
                                pixels[px, py] = color
    return image


def reference_gap_faces(faces):
    # Independently recover each pentagon from its icosahedral vertex normal.
    # The five most outward mesh vertices form that pentagonal face.
    vertices = {p for face in faces for p in face["vertices"]}
    edge_owners = {}
    for face in faces:
        for a, b in zip(face["vertices"], face["vertices"][1:]+face["vertices"][:1]):
            edge = tuple(sorted((a, b)))
            edge_owners[edge] = edge_owners.get(edge, 0)+1
    phi = (1+math.sqrt(5))/2
    directions = [(0, a, b*phi) for a in (-1, 1) for b in (-1, 1)]
    directions += [(a, b*phi, 0) for a in (-1, 1) for b in (-1, 1)]
    directions += [(a*phi, 0, b) for a in (-1, 1) for b in (-1, 1)]
    gaps = []
    for direction in directions:
        normal = [int(math.copysign(math.floor(abs(value)*28/math.sqrt(1+phi*phi)+0.5), value)) for value in direction]
        points = sorted(vertices, key=lambda p: sum(a*b for a,b in zip(p,normal)), reverse=True)[:5]
        center = np.mean(points, axis=0)
        tangent = np.cross(normal, (1, 0, 0) if abs(normal[0]) < 24 else (0, 1, 0))
        bitangent = np.cross(normal, tangent)
        # Equal-length tangent axes make angular ordering independent of tilt.
        tangent = tangent/np.linalg.norm(tangent)
        bitangent = bitangent/np.linalg.norm(bitangent)
        points.sort(key=lambda p: math.atan2(np.dot(np.asarray(p)-center, bitangent), np.dot(np.asarray(p)-center, tangent)))
        first = points.index(min(points))
        points = points[first:]+points[:first]
        assert all(edge_owners[tuple(sorted((a, b)))] == 1 for a, b in zip(points, points[1:]+points[:1])), "Pentagon boundary must close over five original mesh edges"
        neighbors = [i for i,face in enumerate(faces) if len(set(points)&set(face["vertices"]))==2]
        assert len(neighbors)==5
        gaps.append(({"normal":normal,"basis":True,"vertices":points},neighbors))
    gaps.sort(key=lambda gap: min(gap[0]["vertices"]))
    return gaps


def expected_front_color(depth):
    """Camera-light bands, using the independently rotated Z normal."""
    strength = -depth-1
    return 6 if strength < 6 else 4 if strength < 12 else 10 if strength < 18 else 15 if strength < 24 else 1


def darker_color(color):
    palette = (6, 4, 10, 15, 1)
    return palette[max(0, palette.index(color)-1)]


def check_native(args, faces, geometry):
    build = HERE / "build" / args.variant
    output = build / "verification"
    output.mkdir(parents=True, exist_ok=True)
    labels = common.read_labels(build / "main.sym")
    zoom = args.variant == "hexagon"
    shape_toggle = args.variant == "hexagon"
    if zoom:
        assert {"zoomPhase", "zoomScale"} <= labels.keys(), "Hexagon projection has no native zoom state"
    zoom_phases, zoom_scales, zoom_capture_scales = set(), set(), set()
    motion_phases, yaw_speeds, pitch_speeds = set(), set(), set()
    yaw_position_q4 = pitch_position_q4 = 0
    if zoom:
        assert {"motionPhase", "yawFraction", "pitchFraction", "yawSpeed", "pitchSpeed"} <= labels.keys(), "Hexagon rotation has no native fractional motion state"
    pentagon_faces = [face for face, _ in reference_gap_faces(faces)] if shape_toggle else []
    shared_vertices = sorted({point for face in faces for point in face["vertices"]})
    shape_modes, shape_capture_modes = set(), set()
    seen_faces_by_shape = [set(), set()]
    if shape_toggle:
        assert {"shapeMode", "shapePose", "shownShapeMode", "pentFaceVertices"} <= labels.keys(), "Hexagon demo has no native pentagon toggle"
        assert geometry["pentagons"]["maximum_edge_dx"] <= labels["edgeMaxDX"] and geometry["pentagons"]["maximum_edge_dy"] <= labels["edgeMaxDY"], "Pentagon edges exceed their crossing table"
    assert geometry["maximum_edge_dx"] <= labels["edgeMaxDX"], "Projected edge exceeds its crossing table"
    assert geometry["maximum_edge_dy"] <= labels["edgeMaxDY"], "Projected edge exceeds its crossing table"
    program = build / "sprite-ball.prg"
    scene = json.loads((HERE / "build" / "scene.json").read_text())
    artwork = (HERE / scene["source"]).read_bytes()
    expected_bitmap = (HERE / "build" / "ball-bitmap.bin").read_bytes()
    expected_screen = (HERE / "build" / "ball-screen.bin").read_bytes()
    expected_colors = (HERE / "build" / "ball-colors.bin").read_bytes()
    expected_bitmap_b = (HERE / "build" / "ball-bitmap-b.bin").read_bytes()
    expected_screen_b = (HERE / "build" / "ball-screen-b.bin").read_bytes()
    source_checks = [check_scene(artwork, expected_bitmap, expected_screen, expected_colors, scene),
                     check_scene(artwork, expected_bitmap_b, expected_screen_b, expected_colors, scene, phase=1)]
    assert scene.get("source_render_preserved", True) == all(check["initial_pixel_differences"] == 0 for check in source_checks), "Source-render preservation metadata differs from decoded pixels"
    disco = scene.get("disco") if args.variant == "hexagon" else None
    if disco:
        assert "discoPhase" in labels, "Disco background has no native color animation"
    disco_phases = set()
    previous_disco_tick, expected_disco_phase = 0, 15
    palette_file = ROOT / "palettes" / "colodore.vpl"
    colors = [tuple(int(v, 16) for v in line.split()[:3])
              for line in palette_file.read_text().splitlines()
              if line.strip() and not line.startswith("#")]
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = common.vice_command(args.vice, program, port, palette_file)
    frames, samples, transcript = [], [], []
    with (output / "vice.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            with common.connect_monitor(process, port) as connection:
                monitor = common.Monitor(connection)
                monitor.run("r")
                monitor.run("sidefx off")
                if "sceneRunning" in labels:
                    run_checkpoint = checkpoint(monitor, f"break {labels['sceneRunning']:04x}")
                    monitor.run("x")
                    assert monitor.registers()[0] == labels["sceneRunning"], "Scene did not reach its normal RUN entry"
                    monitor.run("bank ram")
                    entry = monitor.memory(output / "run-entry.bin", 0, 0xffff)
                    previous_disco_tick = entry[labels["rasterTick"]]
                    if disco:
                        assert entry[labels["discoPhase"]] == 15, "Background disco did not remain black before RUN"
                    monitor.run("bank cpu")
                    monitor.run(f"delete {run_checkpoint}")
                checkpoint(monitor, f"break {labels['framePresented']:04x}")
                half_checkpoint = checkpoint(monitor, f"break {labels['frameColorsUpdated']:04x}")
                monitor.run(f"disable {half_checkpoint}")
                previous_origin = previous_tick = None
                for index in range(args.frames):
                    monitor.run("x")
                    pc, raster, cycles = monitor.registers()
                    assert pc == labels["framePresented"], f"Unexpected stop: ${pc:04x}"
                    assert raster < 51, "Sprite and disco colors changed after the visible PAL area started"
                    monitor.run("bank ram")
                    ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                    if index == 0:
                        curve_samples = check_edge_curves(ram, labels)
                    assert ram[0x2000:0x3f40] == expected_bitmap, "Field A bitmap changed"
                    assert ram[0x4000:0x5f40] == expected_bitmap_b, "Field B bitmap changed"
                    assert ram[0x7c00:0x7fe8] == expected_screen_b, "Field B screen colors changed"
                    monitor.run("bank io")
                    vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                    color_ram = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                    frame_colors = bytearray(expected_colors)
                    if disco:
                        phase = ram[labels["discoPhase"]]
                        tick = ram[labels["rasterTick"]]
                        for elapsed in range(1, ((tick-previous_disco_tick)&255)+1):
                            if (previous_disco_tick+elapsed)&3 == 1:
                                expected_disco_phase = (expected_disco_phase+1)&15
                        assert phase == expected_disco_phase, "Disco color phase differs from PAL cadence"
                        previous_disco_tick = tick
                        disco_phases.add(phase)
                        shared_color = disco["palette"][phase]
                        assert {color_ram[cell] for cell in disco["cells"]} == {shared_color}, "Circle cells must share one disco color"
                        for cell in disco["cells"]:
                            frame_colors[cell] = shared_color
                    assert color_ram == bytes(frame_colors), "Native Color RAM differs from the circle-only disco palette"
                    monitor.run("bank cpu")
                    yaw, pitch = ram[labels["angleYaw"]], ram[labels["anglePitch"]]
                    expected_yaw = (6*index) & 255
                    expected_pitch = (3*index) & 255
                    if zoom:
                        motion_phase = index&255
                        yaw_speed = motion_speed(motion_phase-1, 8, 96)
                        pitch_speed = motion_speed(motion_phase-65, 4, 64)
                        if index:
                            yaw_position_q4 += yaw_speed
                            pitch_position_q4 += pitch_speed
                        expected_yaw, expected_pitch = (yaw_position_q4//16)&255, (pitch_position_q4//16)&255
                        expected_motion = (motion_phase, yaw_position_q4&15, pitch_position_q4&15, yaw_speed, pitch_speed)
                        native_motion = tuple(ram[labels[name]] for name in ("motionPhase", "yawFraction", "pitchFraction", "yawSpeed", "pitchSpeed"))
                        assert native_motion == expected_motion, (index, native_motion, expected_motion)
                        motion_phases.add(motion_phase)
                        yaw_speeds.add(yaw_speed)
                        pitch_speeds.add(pitch_speed)
                    assert (yaw, pitch) == (expected_yaw, expected_pitch), "Rotation path or phase differs"
                    base = ram[labels["shownMetadataBase"]]
                    screen = 0x400
                    buffer = 0x0c00 + (base // 8) * 512
                    mirror = 0x7800 + (base // 8) * 512
                    assert ram[buffer:buffer+512] == ram[mirror:mirror+512], "VIC banks show different sprite poses"
                    count = ram[labels["usedSprites"]]
                    assert ram[labels["overflowCount"]] == 0, "Runtime sprite overflow"
                    assert ram[labels["missedDeadlines"]] == 0, "Runtime missed a presentation deadline"
                    assert count <= 8
                    assert vic[0x17] == vic[0x1d] == 255 and vic[0x1c] == 0
                    assert vic[0x15] == (1 << count) - 1
                    assert vic[0x10] == 0
                    assert vic[0x1b] == 0 and vic[0x11]&0x60 == 0x20
                    assert vic[0x16]&0x10 and vic[0x21]&15 == scene["background"]
                    assert vic[0x18]&0xfe == 0x18 and vic[0x16]&7 == 0
                    matrix = coefficients(yaw, pitch)
                    shape_mode, shape_pose = 0, None
                    if shape_toggle:
                        cycle_pose = index%200
                        shape_mode = int(cycle_pose >= 150)
                        shape_pose = cycle_pose-150 if shape_mode else cycle_pose
                        native_shape = tuple(ram[labels[name]] for name in ("shapeMode", "shapePose", "shownShapeMode"))
                        assert native_shape == (shape_mode, shape_pose, shape_mode), (index, native_shape, shape_mode, shape_pose)
                        shape_modes.add(shape_mode)
                    frame_faces = pentagon_faces if shape_mode else faces
                    phase, scale = None, None
                    if zoom:
                        phase, scale = index&255, zoom_scale(index&255)
                        assert ram[labels["zoomPhase"]] == phase, "Zoom phase differs from the presentation clock"
                        assert ram[labels["zoomScale"]] == scale, "Zoom scale differs from the intended cosine pulse"
                        matrix = zoom_matrix(matrix, scale)
                        axis_names = ("axisXX", "axisXZ", "axisYX", "axisYY", "axisYZ", "axisZX", "axisZY", "axisZZ")
                        native_matrix = tuple(value if value < 128 else value-256 for value in (ram[labels[name]] for name in axis_names))
                        assert native_matrix == matrix, "Zoom changed the projection coefficients or the unscaled lighting normal"
                        zoom_phases.add(phase)
                        zoom_scales.add(scale)
                    depths = [project(face, matrix)[0] for face in frame_faces]
                    visible_faces = [i for i, depth in enumerate(depths) if depth < 0]
                    # Independent ranked result: preserve the eight strongest
                    # facing depths, resolving equal sizes by the face index.
                    expected_faces = sorted(sorted(visible_faces, key=lambda i: (depths[i], i))[:8])
                    actual_faces = list(ram[labels["slotFace"] + base:labels["slotFace"] + base + count])
                    assert actual_faces == expected_faces, (yaw, pitch, actual_faces, expected_faces)
                    assert count == min(8, len(visible_faces))
                    if shape_toggle:
                        seen_faces_by_shape[shape_mode].update(actual_faces)
                        if shape_mode:
                            assert len(visible_faces) <= 6 and count <= 6, "Pentagon mode exceeded six visible faces"
                    nonempty = 0
                    for slot in range(8):
                        data = ram[buffer + slot * 64:buffer + slot * 64 + 63]
                        if slot >= count:
                            assert data == bytes(63), "An unused sprite retained old pixels"
                            continue
                        face = actual_faces[slot]
                        _, points = project(frame_faces[face], matrix, golden=args.variant == "golden")
                        min_x, min_y = min(x for x, y in points), min(y for x, y in points)
                        expected_color = expected_front_color(depths[face])
                        assert vic[0x27+slot]&15 == expected_color, (index,face,vic[0x27+slot]&15,expected_color)
                        local = [(x - min_x, y - min_y) for x, y in points]
                        size = len(frame_faces[face]["vertices"])
                        if args.variant == "hexagon":
                            table = labels["pentFaceVertices"] if shape_mode else labels["hexFaceVertices"]
                            ids = ram[table+face*size:table+(face+1)*size]
                            native_points = [(ram[labels["sharedX"]+vertex], ram[labels["sharedY"]+vertex]) for vertex in ids]
                            if shape_mode:
                                expected_ids = {shared_vertices.index(point) for point in frame_faces[face]["vertices"]}
                                assert len(ids) == 5 and set(ids) == expected_ids, "Pentagon does not use its five original shared vertices"
                                assert sorted(native_points) == sorted(points), (index, face, native_points, points)
                            else:
                                assert native_points == points, (index, face, native_points, points)
                        else:
                            native_points = [(ram[labels["projectedX"] + face * size + i],
                                              ram[labels["projectedY"] + face * size + i]) for i in range(size)]
                            assert native_points == points, (index, face, native_points, points)
                        expected = polygon_bytes(local)
                        nonempty += bool(any(data))
                        if data != expected:
                            offset = next(i for i, pair in enumerate(zip(data, expected)) if pair[0] != pair[1])
                            raise AssertionError(f"Frame {index}, face {face}, byte {offset}: {data[offset]:02x} != {expected[offset]:02x}")
                        assert vic[slot * 2] == (scene["center"][0]-104+2*min_x)&255
                        assert vic[slot * 2 + 1] == (scene["center"][1]-78+2*min_y)&255
                        assert ram[0x7f8 + slot] == buffer // 64 + slot
                        assert ram[0x7ff8 + slot] == (mirror-0x4000)//64+slot
                    assert ram[screen:screen+1000] == expected_screen, "Static source artwork attributes changed"
                    duration = ram[labels["renderCycles"]] | ram[labels["renderCycles"] + 1] << 8
                    # Conditional palette work moves this CPU checkpoint within
                    # the upper border. Compare the video-frame origins instead.
                    presentation_origin = cycles-raster*63
                    tick = ram[labels["rasterTick"]]
                    if previous_origin is not None:
                        interval = 19656*2
                        assert (tick-previous_tick)&255 == 2, "Presentation skipped a PAL tick"
                        assert abs(presentation_origin-previous_origin-interval) < 64, (index,presentation_origin-previous_origin,duration)
                    previous_origin, previous_tick = presentation_origin, tick
                    samples.append({"yaw": yaw, "pitch": pitch,
                                    "motion_phase": motion_phase if zoom else None,
                                    "yaw_speed_q4": yaw_speed if zoom else None, "pitch_speed_q4": pitch_speed if zoom else None,
                                    "shape_mode": shape_mode, "shape_pose": shape_pose,
                                    "zoom_phase": phase, "zoom_scale_q6": scale,
                                    "disco_phase": ram[labels["discoPhase"]] if disco else None,
                                    "sprite_colors": [vic[0x27+slot]&15 for slot in range(count)],
                                    "sprites": count, "nonempty_sprites": nonempty,
                                    "visible_faces": len(visible_faces), "selected_faces": actual_faces,
                                    "render_cycles": duration, "presentation_cycle": cycles, "raster": raster})
                    frames.append(render_preview(ram, labels, colors, color_ram, scene["background"]))
                    capture = index in ((48, 128, 175) if shape_toggle else (48,))
                    capture_suffix = "-pentagons" if index == 175 else ("-zoom-min" if index == 128 else "")
                    if capture:
                        # A VICE screenshot records the actual VIC output, not the host preview.
                        native_path = output / f"native{capture_suffix}.png"
                        monitor.run(f'screenshot "{native_path}" 2')
                        screenshot = Image.open(native_path).convert("RGB").crop((32, 35, 352, 235))
                        frames[-2].save(output / f"expected-native{capture_suffix}.png")
                        assert np.array_equal(np.asarray(screenshot), np.asarray(frames[-2])), "Native VIC screenshot differs from verified sprites"
                    # Stop on the intervening PAL frame. Its displayed geometry
                    # must stay intact while every active color shifts one shade.
                    monitor.run(f"enable {half_checkpoint}")
                    monitor.run("x")
                    half_pc, half_raster, half_cycles = monitor.registers()
                    assert half_pc == labels["frameColorsUpdated"], "Missing intervening color update"
                    assert abs(half_cycles-half_raster*63-presentation_origin-19656) < 64, "Color update skipped a PAL frame"
                    monitor.run("bank io")
                    half_vic = monitor.memory(output / "half-vic.bin", 0xd000, 0xd03f)
                    half_color_ram = bytes(value & 15 for value in monitor.memory(output / "half-colors.bin", 0xd800, 0xdbe7))
                    assert half_color_ram == color_ram, "Intervening MCI field changed the shared disco palette"
                    half_colors = [value & 15 for value in half_vic[0x27:0x2f]]
                    assert half_vic[0x18]&0xfe == 0xf0, "MCI field B screen not selected"
                    assert half_vic[0x16]&7 == scene["horizontal_phase_shift"], "MCI field B X phase differs"
                    assert half_vic[:0x11] == vic[:0x11] and half_vic[0x15] == vic[0x15], "Intervening frame moved sprites"
                    for slot in range(count):
                        assert half_colors[slot] == darker_color(vic[0x27+slot]&15), "Intervening frame did not darken one shade"
                    monitor.run("bank ram")
                    if shape_toggle:
                        shown_shape = monitor.memory(output / "half-shape.bin", labels["shownShapeMode"], labels["shownShapeMode"])
                        assert shown_shape == bytes([shape_mode]), "Intervening PAL field switched the displayed polygon mode"
                    front = monitor.memory(output / "half-sprites.bin", buffer, buffer+511)
                    assert front == ram[buffer:buffer+512], "Intervening frame changed displayed sprite pixels"
                    field_b_front = monitor.memory(output / "half-mirror.bin", mirror, mirror+511)
                    assert field_b_front == front, "MCI field B sprites differ from field A"
                    shown = monitor.memory(output / "half-shown.bin", labels["shownMetadataBase"], labels["shownMetadataBase"])
                    assert shown == bytes([base]), "Intervening frame swapped sprite buffers"
                    monitor.run("bank cpu")
                    monitor.run(f"disable {half_checkpoint}")
                    samples[-1]["darker_sprite_colors"] = half_colors[:count]
                    if capture:
                        native_a_path = output / f"native-a{capture_suffix}.png"
                        monitor.run(f'screenshot "{native_a_path}" 2')
                        image_a = Image.open(native_a_path).convert("RGB").crop((32, 35, 352, 235))
                        frames[-1].save(output / f"expected-native-a{capture_suffix}.png")
                        assert np.array_equal(np.asarray(image_a), np.asarray(frames[-1])), "Native MCI field A differs"
                        if zoom:
                            zoom_capture_scales.add(scale)
                        if shape_toggle:
                            shape_capture_modes.add(shape_mode)
                    frames.append(render_preview(ram, labels, colors, half_color_ram, scene["background"], half_colors, phase=1, horizontal_shift=scene["horizontal_phase_shift"]))
                    if index % 64 == 0:
                        print(f"Verified native frame {index}/{args.frames}", flush=True)
                transcript = monitor.transcript
        finally:
            if "monitor" in locals():
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    frames[0].resize((640, 400), Image.Resampling.NEAREST).save(output / "preview.png")
    frames[0].save(output / "animation.gif", save_all=True, append_images=frames[1:],
                   duration=20, loop=0,
                   optimize=False, disposal=2)
    if args.variant == "hexagon" and len(samples) >= 64:
        assert max(s["nonempty_sprites"] for s in samples) == 8
        assert {color for sample in samples for color in sample["sprite_colors"]} == {6, 4, 10, 15, 1}
    if disco and len(samples) >= 32:
        assert disco_phases == set(range(16)), "Native run did not exercise every disco palette phase"
    if zoom and len(samples) >= 257:
        assert zoom_phases == set(range(256)) and zoom_scales == set(range(52, 65)), "Native run did not cover the full zoom pulse and wrap"
        assert {52, 64} <= zoom_capture_scales, "Native VIC captures did not cover full size and minimum zoom"
    if shape_toggle and len(samples) >= 401:
        assert shape_modes == {0, 1} and shape_capture_modes == {0, 1}, "Native run did not cover and capture both polygon modes"
        assert seen_faces_by_shape == [set(range(20)), set(range(12))], "Native run did not exercise every face in both polygon modes"
    if zoom and len(samples) >= 513:
        assert motion_phases == set(range(256)) and (min(yaw_speeds), max(yaw_speeds), min(pitch_speeds), max(pitch_speeds)) == (8, 96, 4, 64), "Native run did not cover two full motion periods and their speed ranges"
    (output / "monitor.log").write_text("\n".join(transcript))
    result = {"variant": args.variant, "prg_sha256": hashlib.sha256(program.read_bytes()).hexdigest(), "geometry": geometry,
              "face_selection": "eight_largest_by_facing_depth",
              "rotation": "periodic_positive_q4_speeds" if zoom else "constant_yaw_6_pitch_3",
              "lighting": "camera_facing_rotated_normal_z",
              "lighting_restored_from": "9e10543",
              "brightness": "brighter_toward_camera",
              "sprite_palette": [6, 4, 10, 15, 1], "shade_index_thresholds": [6, 12, 18, 24],
              "color_animation": "normal_then_one_shade_darker_each_pal_frame",
              "native_color_frames": len(samples)*2,
              "background_art_sha256": hashlib.sha256(artwork).hexdigest(),
              "bitmap_mode": "multicolor_interlace" if scene["phase_count"]==2 else "multicolor", "sphere_center": scene["center"],
              "bitmap_passthrough": scene["bitmap_passthrough"], "generated_dithering": scene["generated_dithering"],
              "pentagon_coloring": False, "color_screen_count": 2, "vic_banks": [0, 1], "sprite_buffers_mirrored": True, "color_screen_static": True,
              "shared_color_ram_static": not bool(disco), "disco_color_cells": len(disco["cells"]) if disco else 0,
              "disco_color_phases_verified": sorted(disco_phases), "disco_color_hz": 50.124542124542124/4 if disco else 0,
              "per_frame_color_reset": False,
              "source_artwork_initial_pixel_differences_by_field": [check["initial_pixel_differences"] for check in source_checks],
              "disco_opening_pixels_by_field": [check["opening_pixels"] for check in source_checks],
              "disco_opening_coverage": 1.0 if disco else 0,
              "white_contour_pixel_differences": 0, "runtime_outside_opening_pixel_differences": 0,
              "sprite_priority": "in_front_of_graphics", "bitmap_unchanged_across_frames": True,
              "native_frames": len(samples), "native_sprite_bytes_checked": len(samples) * 504,
              "exact_edge_samples": curve_samples,
              "maximum_nonempty_sprites": max(s["nonempty_sprites"] for s in samples),
              "native_screenshot_pixel_differences": 0 if len(samples)>48 else None,
              "pal_ticks_per_presentation": 2,
              "frames_per_second": 50.124542124542124 / 2,
              "render_cycles_min": min(s["render_cycles"] for s in samples),
              "render_cycles_mean": sum(s["render_cycles"] for s in samples) / len(samples),
              "render_cycles_max": max(s["render_cycles"] for s in samples), "samples": samples}
    if zoom:
        result["motion"] = {"period_presentations": 256, "phases_verified": len(motion_phases),
                            "yaw_speed_q4_range": [min(yaw_speeds), max(yaw_speeds)],
                            "pitch_speed_q4_range": [min(pitch_speeds), max(pitch_speeds)],
                            "fractional_bits": 4, "pitch_profile_delay_presentations": 64}
        result["zoom"] = {"period_presentations": 256, "minimum_scale_q6": 52, "maximum_scale_q6": 64,
                          "phases_verified": len(zoom_phases), "scales_verified": sorted(zoom_scales),
                          "native_capture_scales": sorted(zoom_capture_scales), "lighting_normals_scaled": False}
    if shape_toggle:
        result["polygon_cycle"] = {"hexagon_presentations": 150, "pentagon_presentations": 50,
                                   "cycle_presentations": 200, "modes_verified": sorted(shape_modes),
                                   "native_capture_modes": sorted(shape_capture_modes),
                                   "observed_face_ids_by_mode": [sorted(observed) for observed in seen_faces_by_shape]}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--vice", default=shutil.which("x64sc"))
    parser.add_argument("--geometry-only", action="store_true")
    parser.add_argument("--variant", choices=("baseline", "golden", "hexagon"), default="hexagon")
    args = parser.parse_args()
    if args.frames is None:
        args.frames = 513 if args.variant == "hexagon" else 257
    faces = model("hexagon" if args.variant == "hexagon" else "pentagon")
    geometry = check_bounds(faces, golden=args.variant == "golden", zoom=args.variant == "hexagon")
    if args.variant == "hexagon":
        geometry["pentagons"] = check_bounds([face for face, _ in reference_gap_faces(faces)], golden=False, zoom=True)
    print(json.dumps(geometry), flush=True)
    if not args.geometry_only:
        check_native(args, faces, geometry)


if __name__ == "__main__":
    main()
