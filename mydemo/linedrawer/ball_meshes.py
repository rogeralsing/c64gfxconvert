"""Object-space meshes for the live wireframe ball demos."""

from itertools import combinations
from math import cos, hypot, isclose, pi, sin


RADIUS = 256  # 8.8 fixed point


def _opposite(point):
    return tuple(-value for value in point)


def _outward_face(vertices, face):
    a, b, c = (vertices[index] for index in face[:3])
    ux, uy, uz = (b[axis] - a[axis] for axis in range(3))
    vx, vy, vz = (c[axis] - a[axis] for axis in range(3))
    normal = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    if sum(n * value for n, value in zip(normal, a)) < 0:
        return (face[0], *reversed(face[1:]))
    return face


def _finish(vertices, faces, *, latitude_last=False):
    # Order matching antipodes one half-array apart so rotation can share
    # the three products for each coordinate between opposite vertices.
    first_half = [point for point in sorted(vertices) if point < _opposite(point)]
    paired = tuple(first_half + [_opposite(point) for point in first_half])
    if len(set(paired)) != len(vertices) or set(paired) != set(vertices):
        raise ValueError("Expected one distinct antipode for every ball vertex")
    index = {point: i for i, point in enumerate(paired)}
    faces = tuple(_outward_face(paired, tuple(index[vertices[i]] for i in face))
                  for face in faces)

    adjacent = {}
    for face_index, face in enumerate(faces):
        for a, b in zip(face, (*face[1:], face[0])):
            edge = (min(a, b), max(a, b))
            adjacent.setdefault(edge, []).append(face_index)
    if any(len(incident_faces) != 2 for incident_faces in adjacent.values()):
        raise ValueError("Expected two faces on every ball edge")
    edges = sorted(adjacent)
    if latitude_last:
        # Finish the joins at the poles before drawing the rings. This
        # reduces the intermediate masks that consume reserved characters.
        edges.sort(key=lambda edge: paired[edge[0]][1] == paired[edge[1]][1])
    return paired, faces, tuple(edges), tuple(tuple(adjacent[edge]) for edge in edges)


def _football():
    # Same icosahedron axes as asm/sphere-polygons/meshes.cjs. Cut each
    # directed icosahedron edge one-third of the way from its first vertex.
    phi = (1 + 5 ** 0.5) / 2
    signs = (-1, 1)
    corners = ([(0, a, b * phi) for a in signs for b in signs]
               + [(a, b * phi, 0) for a in signs for b in signs]
               + [(a * phi, 0, b) for a in signs for b in signs])
    neighbors = [tuple(j for j, other in enumerate(corners)
                       if isclose(sum((a - b) ** 2 for a, b in zip(point, other)), 4))
                 for point in corners]
    directed_edges = [(a, b) for a, ring in enumerate(neighbors) for b in ring]
    edge_vertex = {edge: i for i, edge in enumerate(directed_edges)}
    points = [tuple(2 * x + y for x, y in zip(corners[a], corners[b]))
              for a, b in directed_edges]
    scale = RADIUS / hypot(*points[0])
    vertices = [tuple(round(value * scale) for value in point) for point in points]

    faces = []
    for a, ring in enumerate(neighbors):
        ordered = [ring[0]]
        for _ in ring[1:]:
            ordered.append(next(b for b in ring if b in neighbors[ordered[-1]] and b not in ordered))
        faces.append(tuple(edge_vertex[a, b] for b in ordered))

    for a, b, c in combinations(range(len(corners)), 3):
        if b in neighbors[a] and c in neighbors[a] and c in neighbors[b]:
            perimeter = ((a, b), (b, a), (b, c), (c, b), (c, a), (a, c))
            faces.append(tuple(edge_vertex[edge] for edge in perimeter))
    return _finish(vertices, faces)


def _globe():
    # Use the checker topology from asm/sphere-polygons/meshes.cjs with
    # eight meridians and three rings to fit the wireframe font's joins.
    longitude_count = 8
    latitude_bands = 4
    vertices = [(0, RADIUS, 0)]
    for band in range(1, latitude_bands):
        theta = band * pi / latitude_bands
        radius = RADIUS * sin(theta)
        y = round(RADIUS * cos(theta))
        for longitude in range(longitude_count):
            angle = longitude * 2 * pi / longitude_count
            vertices.append((round(radius * sin(angle)), y, round(radius * cos(angle))))
    south = len(vertices)
    vertices.append((0, -RADIUS, 0))

    def ring(band, longitude):
        return 1 + (band - 1) * longitude_count + longitude % longitude_count

    faces = []
    for longitude in range(longitude_count):
        following = longitude + 1
        faces.append((0, ring(1, longitude), ring(1, following)))
        for band in range(1, latitude_bands - 1):
            faces.append((ring(band, longitude), ring(band, following),
                          ring(band + 1, following), ring(band + 1, longitude)))
        faces.append((ring(latitude_bands - 1, longitude), south,
                      ring(latitude_bands - 1, following)))
    return _finish(vertices, faces, latitude_last=True)


def make_mesh(name):
    """Return vertices, outward faces, unique edges, and their adjacent faces."""
    return {"football": _football, "globe": _globe}[name]()
