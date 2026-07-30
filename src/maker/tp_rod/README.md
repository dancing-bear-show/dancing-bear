# TP Rod (Fixed Length)

Simple fixed-length toilet paper rod for holders without springs.

Status
- Generator present: `tp_rod/gen_tp_rod.py`
- Defaults: 170 mm length, Ø24 mm; chamfered ends
- Output: `tp_rod_170mm_d24mm.stl` (example)

Defaults
- Length: 170 mm end-to-end
- Diameter: 24 mm (adjust as needed)
- Chamfer: 1.0 mm on ends

Files
- `gen_tp_rod.py` – generates an STL via trimesh
- Output: `tp_rod_170mm_d24mm.stl`

Usage
```
cd maker
make venv
source .venv/bin/activate
python tp_rod/gen_tp_rod.py --length 170 --diameter 24 --outfile tp_rod_170mm_d24mm.stl
```
