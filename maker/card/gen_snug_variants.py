#!/usr/bin/env python3
"""
Generate snug-fit card variants using existing card geometry for base size/centers.
Requires: numpy, shapely, trimesh

Outputs:
- card_2x_halfoz_snug_25p2mm.stl (PLA)
- card_2x_halfoz_snug_25p4mm.stl (PETG)
"""
from pathlib import Path
import math
import numpy as np
import shapely.geometry as sg
import shapely.affinity as sa
import shapely.ops as so
import trimesh

SRC = Path(__file__).resolve().parent
CARD_STL = SRC / 'card_2x_halfoz.stl'


def estimate_centers_and_base(stl_path: Path):
    mesh = trimesh.load_mesh(stl_path, force='mesh')
    bounds = mesh.bounds  # [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    xmin, ymin, zmin = bounds[0]
    xmax, ymax, zmax = bounds[1]
    width = xmax - xmin
    height = ymax - ymin
    thickness = zmax - zmin

    # Use near-vertical faces to detect interior cylindrical holes
    normals = mesh.face_normals
    faces = mesh.faces
    verts = mesh.vertices
    mask = np.abs(normals[:, 2]) < 0.2
    XY = verts[faces[mask].reshape(-1)][:, :2]

    # Keep interior points away from outer boundary
    margin = 5.0
    dx = np.minimum(XY[:, 0] - xmin, xmax - XY[:, 0])
    dy = np.minimum(XY[:, 1] - ymin, ymax - XY[:, 1])
    keep = (dx > margin) & (dy > margin)
    XYi = np.unique(XY[keep], axis=0)
    if len(XYi) < 20:
        # Fallback: assume centers along X near +/- 16mm and Y=0
        centers = np.array([[-16.0, 0.0], [16.0, 0.0]])
        return (width, height, thickness), centers

    # K-means (K=2) along X extremes
    order = np.argsort(XYi[:, 0])
    centers = XYi[np.linspace(0, len(order) - 1, 2).astype(int)]
    for _ in range(50):
        dists = ((XYi[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = dists.argmin(axis=1)
        new_centers = np.vstack([XYi[labels == k].mean(axis=0) for k in range(2)])
        if np.allclose(new_centers, centers, atol=1e-4):
            break
        centers = new_centers

    # Sort by X
    centers = centers[np.argsort(centers[:, 0])]
    return (width, height, thickness), centers


def build_card(width, height, thickness, centers, hole_diameter):
    # Base rectangle centered at origin for convenience
    base = sg.box(-width / 2.0, -height / 2.0, width / 2.0, height / 2.0)
    # Shift centers so that origin is (0,0) at rectangle center
    # The STL bounds were centered around ~0 in provided files, so keep it 0-centered
    holes = []
    r = hole_diameter / 2.0
    for cx, cy in centers:
        holes.append(sg.Point(cx, cy).buffer(r, resolution=64))
    shape = so.unary_union([base] + [sg.Point(0, 0)])  # force polygon
    for h in holes:
        shape = shape.difference(h)

    # Extrude
    mesh = trimesh.creation.extrude_polygon(shape, height=thickness)
    # Position thickness to match original (z from -th/2 to +th/2)
    mesh.apply_translation([0, 0, -thickness / 2.0])
    return mesh


def main():
    (width, height, thickness), centers = estimate_centers_and_base(CARD_STL)
    # Target: snug for 1/2 oz Maple Leaf (25.0 mm coin diameter)
    variants = [
        (25.2, 'card_2x_halfoz_snug_25p2mm.stl'),  # PLA
        (25.4, 'card_2x_halfoz_snug_25p4mm.stl'),  # PETG
    ]
    for dia, name in variants:
        mesh = build_card(width, height, thickness, centers, dia)
        out = SRC / name
        mesh.export(out)
        print(f'Wrote {out} (hole Ø {dia} mm)')


if __name__ == '__main__':
    main()

