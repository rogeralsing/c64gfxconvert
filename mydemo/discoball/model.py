#!/usr/bin/env python3
"""Build independent soccer-ball patches, without prepared animation frames."""

import argparse
from collections import defaultdict
import json
from itertools import combinations
import math
from pathlib import Path

RADIUS = 28
HEXAGON_RADIUS = 24
HEXAGON_CORNERS = ((1, 1, 0), (1, 0, 1), (1, -1, 1),
                   (1, -1, 0), (1, 0, -1), (1, 1, -1))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def normalized(a):
    length = math.sqrt(dot(a, a))
    return tuple(x / length for x in a)


def rounded(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def model(shape="pentagon"):
    phi = (1 + math.sqrt(5)) / 2
    corners = [(0, a, b * phi) for a in (-1, 1) for b in (-1, 1)]
    corners += [(a, b * phi, 0) for a in (-1, 1) for b in (-1, 1)]
    corners += [(a * phi, 0, b) for a in (-1, 1) for b in (-1, 1)]
    if shape == "hexagon":
        return hexagons(corners)
    scale = RADIUS / math.sqrt(1 + phi * phi)
    faces = []
    for corner in corners:
        neighbors = [p for p in corners
                     if abs(sum((x - y) ** 2 for x, y in zip(p, corner)) - 4) < 1e-6]
        normal = normalized(corner)
        tangent = normalized(cross(normal, (1, 0, 0) if abs(normal[0]) < 0.9 else (0, 1, 0)))
        bitangent = cross(normal, tangent)
        neighbors.sort(key=lambda p: math.atan2(dot(p, bitangent), dot(p, tangent)))
        vertices = [tuple(rounded((2 * a + b) * scale / 3)
                          for a, b in zip(corner, neighbor)) for neighbor in neighbors]
        faces.append({"normal": [rounded(x * scale) for x in corner], "vertices": vertices})
    return faces


def hexagons(corners):
    """All twenty hexagons; runtime selects the eight largest visible faces."""
    faces = []
    scale = HEXAGON_RADIUS / math.sqrt(dot(corners[0], corners[0]))
    for triangle in combinations(corners, 3):
        if any(abs(sum((x-y)**2 for x, y in zip(a, b))-4) > 1e-6
               for a, b in combinations(triangle, 2)):
            continue
        a, b, c = triangle
        center = tuple((x+y+z)/3 for x, y, z in zip(a, b, c))
        basis = [tuple(rounded(x*scale) for x in center),
                 tuple(rounded((x-z)*scale/3) for x, z in zip(a, c)),
                 tuple(rounded((y-z)*scale/3) for y, z in zip(b, c))]
        vertices = [tuple(sum(weight*basis[i][axis] for i, weight in enumerate(weights))
                          for axis in range(3)) for weights in HEXAGON_CORNERS]
        normal = [rounded(v*RADIUS) for v in normalized(center)]
        faces.append({"normal": normal, "basis": basis, "vertices": vertices})
    if len(faces) != 20:
        raise ValueError("Expected twenty hexagons")
    normals = {tuple(face["normal"]) for face in faces}
    if any(tuple(-v for v in normal) not in normals for normal in normals):
        raise ValueError("Colored hexagons must form opposite pairs")
    return faces


def multiply(a, b):
    # Same Q6 quarter-square identity as the main demo, including its rounding.
    return ((a + b) ** 2 // 256) - ((a - b) ** 2 // 256)


def coordinate_product(a, b):
    return rounded(a*b/64)


def coefficients(yaw, pitch):
    sine = lambda angle: rounded(64 * math.sin((angle & 255) * math.tau / 256))
    sy, cy, sp, cp = sine(yaw), sine(yaw + 64), sine(pitch), sine(pitch + 64)
    return (cy, sy, multiply(sp, sy), cp, -multiply(sp, cy),
            -multiply(cp, sy), sp, multiply(cp, cy))


def project(face, matrix, golden=False):
    xx, xz, yx, yy, yz, zx, zy, zz = matrix
    n = face["normal"]
    depth = multiply(n[0], zx) + multiply(n[1], zy) + multiply(n[2], zz)
    points = [(64 + multiply(x, xx) + multiply(z, xz),
               64 - multiply(x, yx) - multiply(y, yy) - multiply(z, yz))
              for x, y, z in face["vertices"]]
    if "basis" in face:
        depth = coordinate_product(n[0], zx)+coordinate_product(n[1], zy)+coordinate_product(n[2], zz)
        # Shared 3D vertices must have one projection, independent of which
        # face references them. Rounding separate C/U/V products violates this.
        points = [(64+coordinate_product(x, xx)+coordinate_product(z, xz),
                   64-coordinate_product(x, yx)-coordinate_product(y, yy)-coordinate_product(z, yz))
                  for x, y, z in face["vertices"]]
    if golden:
        inverse_phi = (math.sqrt(5) - 1) / 2
        p0, p2, p4 = points[0], points[2], points[4]
        points[1] = tuple(p0[i] + rounded(inverse_phi * (p2[i] - p4[i])) for i in range(2))
        points[3] = tuple(p4[i] + rounded(inverse_phi * (p2[i] - p0[i])) for i in range(2))
    return depth, points


def write_hexagon_projection(faces, output):
    """Project shared antipodal vertex pairs once, retaining live rotation angles."""
    vertices = sorted({point for face in faces for point in face["vertices"]})
    vertex_index = {point: index for index, point in enumerate(vertices)}
    pairs = [(index, vertex_index[tuple(-v for v in point)])
             for index, point in enumerate(vertices) if point < tuple(-v for v in point)]
    coordinates = sorted({v for face in faces for point in face["vertices"]+[face["normal"]]
                          for v in point if v})
    names = {v: f"hexProduct{'N' if v<0 else 'P'}{abs(v)}" for v in coordinates}
    products = bytearray()
    lines = ["// Generated static-coordinate multiplication, not animation data."]
    for coordinate in coordinates:
        lines.append(f".label {names[coordinate]} = $8000+{len(products)}")
        products.extend(coordinate_product(coordinate, i if i<128 else i-256) & 255
                        for i in range(256))
    def load(coordinate, axis):
        return ([f"    ldx {axis}", f"    lda {names[coordinate]},x"]
                if coordinate else ["    lda #0"])
    lines += ["renderHexagons:", "    jsr cullHexagons", "    jsr selectLargestHexagons",
              "    jsr projectSharedVertices"]
    for index in range(len(faces)):
        lines += [f"    lda faceDepths+{index}", "    bpl !hidden+", "    sta normalDepth",
                  f"    lda #{index}", "    sta faceIndex", "    jsr projectFace",
                  "    jsr drawFace", "!hidden:"]
    lines += ["    rts", "cullHexagons:"]
    normal_index = {tuple(face["normal"]): index for index, face in enumerate(faces)}
    for index, face in enumerate(faces):
        opposite = normal_index[tuple(-v for v in face["normal"])]
        if index > opposite:
            continue
        x, y, z = face["normal"]
        lines += load(x, "axisZX")+["    sta pointTerm"]
        lines += load(y, "axisZY")+["    clc", "    adc pointTerm", "    sta pointTerm"]
        lines += load(z, "axisZZ")+["    clc", "    adc pointTerm", f"    sta faceDepths+{index}"]
        lines += ["    eor #$ff", "    clc", "    adc #1", f"    sta faceDepths+{opposite}"]
    def lookup(coordinate, register, operation="lda"):
        return [f"    {operation} {names[coordinate]},{register}" if coordinate
                else f"    {operation} #0"]
    lines += ["    rts", "projectSharedVertices:", "    ldx axisXX", "    ldy axisXZ"]
    for index, opposite in pairs:
        x, _, z = vertices[index]
        lines += lookup(x, "x")+["    clc"]+lookup(z, "y", "adc")
        lines += ["    clc", "    adc #64", f"    sta sharedX+{index}",
                  "    eor #$ff", "    sec", "    adc #128", f"    sta sharedX+{opposite}"]
    lines += ["    ldx axisYX", "    ldy axisYY"]
    for index, _ in pairs:
        x, y, _ = vertices[index]
        lines += lookup(x, "x")+["    clc"]+lookup(y, "y", "adc")
        lines += [f"    sta sharedY+{index}"]
    lines += ["    ldx axisYZ"]
    for index, opposite in pairs:
        _, _, z = vertices[index]
        lines += lookup(z, "x")+["    clc", f"    adc sharedY+{index}", "    sta pointTerm",
                                    "    lda #64", "    sec", "    sbc pointTerm",
                                    f"    sta sharedY+{index}", "    eor #$ff", "    sec",
                                    "    adc #128", f"    sta sharedY+{opposite}"]
    lines += ["    rts", "hexFaceVertices: .byte "+",".join(
        str(vertex_index[point]) for face in faces for point in face["vertices"])]
    (output / "hex-projection.asm").write_text("\n".join(lines)+"\n")
    (output / "hex-products.bin").write_bytes(products)
    holes = write_gap_topology(faces, vertex_index, output)
    write_pentagon_projection(holes, names, output)


def write_gap_topology(faces, vertex_index, output):
    """Export the twelve shared-vertex pentagons and neighboring hexagons."""
    edges = defaultdict(list)
    for index, face in enumerate(faces):
        ids = [vertex_index[p] for p in face["vertices"]]
        for a, b in zip(ids, ids[1:]+ids[:1]):
            edges[tuple(sorted((a, b)))].append(index)
    boundary = defaultdict(list)
    for (a, b), owners in edges.items():
        if len(owners) == 1:
            boundary[a].append(b)
            boundary[b].append(a)
    remaining, holes = set(boundary), []
    vertices = {index: point for point, index in vertex_index.items()}
    corner_normals = [face["normal"] for face in model("pentagon")]
    while remaining:
        current = min(remaining)
        ids, previous = [current], None
        while True:
            following = next(v for v in boundary[current] if v != previous)
            if following == ids[0]:
                break
            ids.append(following)
            previous, current = current, following
        remaining.difference_update(ids)
        if len(ids) != 5:
            raise ValueError("Expected a pentagonal gap")
        center = tuple(sum(vertices[index][axis] for index in ids) for axis in range(3))
        # Use the original icosahedron direction, as for the hexagon normals;
        # quantized mesh centroids would change the normal's lighting strength.
        normal = max(corner_normals, key=lambda value: dot(value, center))
        area = tuple(sum(cross(vertices[a], vertices[b])[axis]
                         for a, b in zip(ids, ids[1:]+ids[:1])) for axis in range(3))
        if dot(area, normal) < 0:
            ids = ids[:1] + ids[:0:-1]
        neighbors = sorted({edges[tuple(sorted((a, b)))][0]
                            for a, b in zip(ids, ids[1:]+ids[:1])})
        holes.append({"vertices": ids, "neighbors": neighbors, "normal": normal})
    if len(holes) != 12:
        raise ValueError("Expected twelve pentagons")
    normals = {tuple(hole["normal"]) for hole in holes}
    if len(normals) != 12 or any(tuple(-value for value in normal) not in normals for normal in normals):
        raise ValueError("Pentagon normals must form six opposite pairs")
    (output / "hex-gaps.json").write_text(json.dumps(holes, indent=2)+"\n")
    return holes


def write_pentagon_projection(holes, products, output):
    """Cull and gather pentagons from the same projected mesh as the hexagons."""
    samples = bytes(coordinate_product(24, value if value < 128 else value-256) & 255
                    for value in range(256))
    (output / "pent-products.bin").write_bytes(samples)
    lines = ["// Static pentagon topology and normal products, not animation frames.",
             "renderPentagons:", "    jsr cullPentagons", "    jsr projectSharedVertices"]
    for index in range(len(holes)):
        lines += [f"    lda faceDepths+{index}", "    bpl !hidden+", "    sta normalDepth",
                  f"    lda #{index}", "    sta faceIndex", "    jsr projectPentagonFace",
                  "    jsr drawFace", "!hidden:"]
    lines += ["    rts", "cullPentagons:"]

    def load(coordinate, axis):
        if abs(coordinate) == 24:
            result = [f"    ldx {axis}", "    lda pentProductP24,x"]
            if coordinate < 0:
                result += ["    eor #$ff", "    clc", "    adc #1"]
            return result
        return [f"    ldx {axis}", f"    lda {products[coordinate]},x"]

    normal_index = {tuple(hole["normal"]): index for index, hole in enumerate(holes)}
    for index, hole in enumerate(holes):
        opposite = normal_index[tuple(-value for value in hole["normal"])]
        if index > opposite:
            continue
        terms = [(value, axis) for value, axis in zip(hole["normal"], ("axisZX", "axisZY", "axisZZ")) if value]
        if len(terms) != 2:
            raise ValueError("Expected two nonzero icosahedron normal coordinates")
        lines += load(*terms[0]) + ["    sta pointTerm"]
        lines += load(*terms[1]) + ["    clc", "    adc pointTerm", f"    sta faceDepths+{index}"]
        lines += ["    eor #$ff", "    clc", "    adc #1", f"    sta faceDepths+{opposite}"]
    lines += ["    rts", "projectPentagonFace:", "    ldx faceIndex", "    lda pentFaceOffsets,x",
              "    sta faceVertexStart", "    tay", "    lda pentFaceVertices,y", "    tax",
              "    lda sharedX,x", "    sta minX", "    lda sharedY,x", "    sta minY", "    iny"]
    for _ in range(1, 5):
        lines += ["    lda pentFaceVertices,y", "    tax", "    lda sharedX,x", "    cmp minX",
                  "    bcs !notMinX+", "    sta minX", "!notMinX:", "    lda sharedY,x",
                  "    cmp minY", "    bcs !notMinY+", "    sta minY", "!notMinY:", "    iny"]
    lines += ["    ldy faceVertexStart"]
    for point in range(5):
        lines += ["    lda pentFaceVertices,y", "    tax", "    lda sharedX,x", "    sec",
                  "    sbc minX", f"    sta localX+{point}", "    lda sharedY,x", "    sec",
                  "    sbc minY", f"    sta localY+{point}", "    iny"]
    lines += ["    rts", "pentFaceOffsets: .byte " + ",".join(str(index*5) for index in range(len(holes))),
              "pentFaceVertices: .byte " + ",".join(str(index) for hole in holes for index in hole["vertices"])]
    (output / "pent-projection.asm").write_text("\n".join(lines)+"\n")


def write_edge_curves(output, maximum_dx=23, maximum_dy=20):
    """Exact short-edge crossings, shared by all faces and all rotations."""
    curves, low, high = bytearray(), bytearray(), bytearray()
    for dy in range(-20, 21):
        for dx in range(24):
            address = 0xa000+len(curves)
            low.append(address & 255)
            high.append(address >> 8)
            if dx <= maximum_dx:
                curves.extend(20-((-n*dy)//dx) for n in range(dx))
    for name, values in (("low", low), ("high", high), ("samples", curves)):
        (output / f"hex-edge-{name}.bin").write_bytes(values)
    (output / "edge-curves.asm").write_text(
        f".label edgeMaxDX = {maximum_dx}\n.label edgeMaxDY = {maximum_dy}\n")
    if maximum_dx == 9 and maximum_dy == 10:
        # Transpose the used pointers into one indexed page for each byte.
        offsets = [(dy+20)*24+dx for dx in range(1, 10) for dy in range(-10, 11)]
        for name, values in (("low", low), ("high", high)):
            (output / f"hex-edge-compact-{name}.bin").write_bytes(bytes(values[i] for i in offsets))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--shape", choices=("pentagon", "hexagon"), default="pentagon")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    faces = model(args.shape)
    lines = ["// Generated by model.py. Static geometry only."]
    for axis, name in enumerate("XYZ"):
        values = [face["normal"][axis] for face in faces]
        lines += [f"normal{name}: .byte " + ",".join(str(v & 255) for v in values)]
        values = [p[axis] for face in faces for p in face.get("basis", face["vertices"])]
        lines += [f"model{name}: .byte " + ",".join(str(v & 255) for v in values)]
    (args.output / "model.asm").write_text("\n".join(lines) + "\n")
    radius = HEXAGON_RADIUS if args.shape == "hexagon" else RADIUS
    (args.output / "model.json").write_text(json.dumps({"shape": args.shape, "radius": radius, "faces": faces}, indent=2) + "\n")
    # Exhaustive native verification proves every hexagon edge fits nine X steps.
    write_edge_curves(args.output, maximum_dx=9 if args.shape == "hexagon" else 23,
                      maximum_dy=10 if args.shape == "hexagon" else 20)
    if args.shape == "hexagon":
        write_hexagon_projection(faces, args.output)


if __name__ == "__main__":
    main()
