"""Static quad topology and reference projection for thin-face simplification on the globe."""

from collections import Counter, defaultdict
from functools import cache
from typing import NamedTuple

import ball_model
import cube_model
from ball_meshes import make_mesh
from clip_reference import visible_segment


class OppositeEdges(NamedTuple):
    face: int
    neighbor_a: int
    neighbor_b: int
    edge_a: int
    edge_b: int
    vertices: tuple


@cache
def opposite_edges():
    _, faces, edges, adjacent = make_mesh("globe")
    edge_index = {edge: index for index, edge in enumerate(edges)}
    pairs = []
    for face, ring in enumerate(faces):
        if len(ring) != 4:
            continue
        for offset in (0, 1):
            a, b, c, d = ring[offset:] + ring[:offset]
            edge_a = edge_index[tuple(sorted((a, b)))]
            edge_b = edge_index[tuple(sorted((c, d)))]
            neighbor_a = next(other for other in adjacent[edge_a] if other != face)
            neighbor_b = next(other for other in adjacent[edge_b] if other != face)
            pairs.append(OppositeEdges(face, neighbor_a, neighbor_b, edge_a, edge_b, (a, b, c, d)))
    return pairs


def _simplify(points, visible_faces, silhouette):
    """Redirect inner endpoints onto the silhouette of a strip up to two fat pixels wide."""
    removed = set()
    redirects = {}
    if any(not (0 <= x < 160 and 0 <= y < 100) for x, y in points):
        return points, removed

    def distance(a, b):
        ax, ay = points[a]
        bx, by = points[b]
        return max(abs(ax - bx), abs(ay - by))

    for face, neighbor_a, neighbor_b, edge_a, edge_b, vertices in opposite_edges():
        if not visible_faces[face] or visible_faces[neighbor_a] == visible_faces[neighbor_b]:
            continue
        outer_a, outer_b, inner_b, inner_a = vertices
        interior_edge = edge_b
        if visible_faces[neighbor_a]:
            outer_a, outer_b, inner_b, inner_a = inner_a, inner_b, outer_b, outer_a
            interior_edge = edge_a
        if distance(outer_a, outer_b) < 8:
            continue
        if max(distance(outer_a, inner_a), distance(outer_b, inner_b)) > 2:
            continue
        removed.add(interior_edge)
        for outer, inner in ((outer_a, inner_a), (outer_b, inner_b)):
            if inner in silhouette:
                continue
            previous = redirects.get(inner)
            if previous is None or distance(inner, outer) < distance(inner, previous):
                redirects[inner] = outer

    return [points[redirects.get(i, i)] for i in range(len(points))], removed


def frame(index, size=cube_model.SIZE_DEFAULT):
    _, diagonals, edges, adjacent = ball_model.mesh_geometry("globe")
    points = ball_model.frame_vertices("globe", index, size, camera=ball_model.HOLES_CAMERA,
                                      y_sweep=ball_model.HOLES_Y_SWEEP)
    front = [cube_model.face_is_visible(points, face) for face in diagonals]
    silhouette = {vertex for edge, (left, right) in zip(edges, adjacent)
                  if front[left] != front[right] for vertex in edge}
    points, removed = _simplify(points, front, silhouette)
    lines = []
    for edge, ((a, b), (left, right)) in enumerate(zip(edges, adjacent)):
        if edge in removed or not (front[left] or front[right]):
            continue
        clipped = visible_segment((*points[a], *points[b]))
        if clipped is not None:
            lines.append(clipped)
    return lines, removed


def frame_segments(index, size=cube_model.SIZE_DEFAULT):
    return frame(index, size)[0]


def expected(index, lookup):
    """Exact unions in touched cells, with the number of slots required for private joins."""
    lines, removed = frame(index)
    masks = {}
    collisions = set()
    bank_misses = set()
    busy = 0
    for line in lines:
        for cell, stamp in cube_model.normalized_cells(*line):
            previous = masks.get(cell, 0)
            merged = previous | stamp
            if previous and merged not in (previous, stamp):
                collisions.add(cell)
                busy += 1
                if merged not in lookup:
                    bank_misses.add(cell)
            masks[cell] = merged
    return masks, Counter(removed=len(removed), slots=len(collisions),
                          afterLookup=len(bank_misses), busy=busy)


def _gate_edges(pairs):
    """Test the smaller side of each bipartite component of opposite quad edges."""
    graph = defaultdict(set)
    for pair in pairs:
        graph[pair.edge_a].add(pair.edge_b)
        graph[pair.edge_b].add(pair.edge_a)
    visited = set()
    gate = []
    for root in graph:
        if root in visited:
            continue
        colors = {root: 0}
        pending = [root]
        while pending:
            edge = pending.pop()
            for opposite in graph[edge]:
                if opposite in colors:
                    assert colors[opposite] != colors[edge]
                else:
                    colors[opposite] = 1 - colors[edge]
                    pending.append(opposite)
        visited.update(colors)
        sides = [[edge for edge, color in colors.items() if color == side] for side in (0, 1)]
        gate.extend(min(sides, key=len))
    assert len(gate) == 16
    assert all(pair.edge_a in gate or pair.edge_b in gate for pair in pairs)
    return gate


def write_native(output):
    """Emit fixed topology. The 6510 reads the projected endpoints and visibility each frame."""
    pairs = opposite_edges()
    vertices, faces, edges, _ = make_mesh("globe")
    table_names = ("thinTestFace", "thinF0", "thinF2", "thinE0", "thinE2",
                   "thinA", "thinB", "thinC", "thinD")
    rows = [(*pair[:5], *(2 * vertex for vertex in pair.vertices)) for pair in pairs]
    tables = dict(zip(table_names, zip(*rows)))
    offsets = []
    incident = []
    for vertex in range(len(vertices)):
        offsets.extend((len(incident), 0))  # indexed by the byte offset of the projected vertex
        incident.extend(face for face, ring in enumerate(faces) if vertex in ring)
        incident.append(255)
    tables["thinIncidentStart"] = offsets
    tables["thinIncident"] = incident
    (output / "thin-topology.bin").write_bytes(bytes(value for column in tables.values() for value in column))
    gate = _gate_edges(pairs)
    (output / "thin-gate.bin").write_bytes(bytes(2 * vertex for edge in gate for vertex in edges[edge]))
