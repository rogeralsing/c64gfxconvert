"""Object-space ball tables and the reference for their live C64 renderer."""

from functools import cache

import cube_model as cube
from ball_meshes import make_mesh
from clip_reference import visible_segment

CAMERA_DEPTH = 1088
MOTION_AMPLITUDES = (64, 64, 192)
DEFAULT_CAMERA = (CAMERA_DEPTH, MOTION_AMPLITUDES[2])
HOLES_CAMERA = (610, 13)  # center and Z sweep, in 8.8
HOLES_Y_SWEEP = 9


@cache
def mesh_geometry(shape):
    vertices, faces, edges, edge_faces = make_mesh(shape)
    # The native rotation computes one vertex from each antipodal pair.
    half = tuple(tuple((coordinate + 2) >> 2 for coordinate in vertex)
                 for vertex in vertices[:len(vertices) // 2])
    diagonals = tuple(tuple(face[i] for i in (0, len(face) // 4, len(face) // 2, len(face) * 3 // 4))
                      for face in faces)
    return half, diagonals, edges, edge_faces


def rotation_matrix(yaw, pitch, roll):
    def q6_sin(phase):
        return (cube.SIN[phase & 255] + 2) >> 2

    def multiply(a, b):
        return (a * b) >> 6

    def clamp(value):
        return max(-64, min(64, value))

    sy, cy = q6_sin(yaw), q6_sin(yaw + 64)
    sp, cp = q6_sin(pitch), q6_sin(pitch + 64)
    sr, cr = q6_sin(roll), q6_sin(roll + 64)
    yx, yz = multiply(sp, sy), -multiply(sp, cy)
    return (
        (clamp(multiply(cr, cy) - multiply(sr, yx)), -multiply(sr, cp),
         clamp(multiply(cr, sy) - multiply(sr, yz))),
        (clamp(multiply(sr, cy) + multiply(cr, yx)), multiply(cr, cp),
         clamp(multiply(sr, sy) + multiply(cr, yz))),
        (-multiply(cp, sy), sp, multiply(cp, cy)),
    )


def frame_vertices(shape, n, size=cube.SIZE_DEFAULT, *, camera=DEFAULT_CAMERA, y_sweep=MOTION_AMPLITUDES[1]):
    half, _, _, _ = mesh_geometry(shape)
    matrix = rotation_matrix(cube.YAW0 + n * cube.YAW_INC,
                             cube.PITCH0 + n * cube.PITCH_INC,
                             cube.ROLL0 + n * cube.ROLL_INC)
    rotated = [tuple(sum(a * b for a, b in zip(vertex, row)) >> 4 for row in matrix)
               for vertex in half]
    rotated.extend(tuple(-coordinate for coordinate in vertex) for vertex in rotated[:])
    camera_depth, z_sweep = camera
    sx, sy, sz = (cube.SIN[(phase + n * increment) & 255] * amplitude >> 8
                  for phase, increment, amplitude in zip(cube.POSITION_PHASES,
                                                         cube.POSITION_INCREMENTS,
                                                         (MOTION_AMPLITUDES[0], y_sweep, z_sweep)))
    size = max(cube.SIZE_MIN, min(cube.SIZE_MAX, size))
    inverse = cube.SIZE_INVERSE[size - cube.SIZE_MIN]
    position = (sx * inverse >> 8, sy * inverse >> 8, (camera_depth + sz) * inverse >> 8)
    return cube.project_vertices(rotated, position)


def frame_segments(shape, n, size=cube.SIZE_DEFAULT, *, camera=DEFAULT_CAMERA, y_sweep=MOTION_AMPLITUDES[1]):
    _, diagonals, edges, edge_faces = mesh_geometry(shape)
    points = frame_vertices(shape, n, size, camera=camera, y_sweep=y_sweep)
    front = [cube.face_is_visible(points, face) for face in diagonals]
    segments = []
    for (a, b), (left, right) in zip(edges, edge_faces):
        if front[left] or front[right]:
            clipped = visible_segment((*points[a], *points[b]))
            if clipped is not None:
                segments.append(clipped)
    return segments


def frame_screen(shape, n, tile_to_code):
    return cube.segment_screen(frame_segments(shape, n), tile_to_code)


def emit(shape, output):
    half, diagonals, edges, edge_faces = mesh_geometry(shape)
    # Each column is contiguous so the 6510 can index it with a byte.
    streams = (*zip(*half), *zip(*diagonals), *zip(*edges), *zip(*edge_faces))
    data = bytes((value * 2 if 3 <= index < 9 else value) & 255
                 for index, stream in enumerate(streams) for value in stream)
    (output / f"{shape}-mesh.bin").write_bytes(data)
    return len(half) * 2, len(diagonals), len(edges)
