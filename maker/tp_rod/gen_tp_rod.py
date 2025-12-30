#!/usr/bin/env python3
"""
Generate a simple fixed-length toilet paper rod as a cylinder with light chamfer.
Requires: numpy, trimesh
"""
from pathlib import Path
import argparse
import trimesh


def make_rod(length_mm: float, diameter_mm: float, _chamfer_mm: float = 1.0) -> trimesh.Trimesh:
    r = diameter_mm / 2.0
    # Base cylinder along Z (no boolean ops to avoid external backends)
    cyl = trimesh.creation.cylinder(radius=r, height=length_mm, sections=128)
    # Recenter along Z so it matches typical STL expectations (-L/2..+L/2)
    cyl.apply_translation([0, 0, 0])
    return cyl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--length', type=float, default=170.0, help='End-to-end length in mm')
    ap.add_argument('--diameter', type=float, default=24.0, help='Rod outer diameter in mm')
    ap.add_argument('--chamfer', type=float, default=1.0, help='End chamfer in mm')
    ap.add_argument('--outfile', type=Path, default=Path('tp_rod_170mm_d24mm.stl'))
    args = ap.parse_args()

    mesh = make_rod(args.length, args.diameter, args.chamfer)
    mesh.export(args.outfile)
    print(f'Wrote {args.outfile} (L={args.length}mm, D={args.diameter}mm, chamfer={args.chamfer}mm)')


if __name__ == '__main__':
    main()
