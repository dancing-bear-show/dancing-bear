# Next Steps (Printing + Fit)

Context
- Snug variants generated: `card_2x_halfoz_snug_25p2mm.stl` (PLA), `card_2x_halfoz_snug_25p4mm.stl` (PETG).
- TP rod generated: `tp_rod_170mm_d24mm.stl` (fixed 170 mm length, Ø24 mm).

1) Printer Setup (pick one)
- OctoPrint:
  - Install OctoPi on a Pi, connect Anycubic via USB.
  - Get API key from Settings → API.
- Moonraker (Klipper):
  - Install Mainsail/Fluidd, connect printer, confirm web UI.

2) Slice to G-code
- Use your slicer (PrusaSlicer/Orca/Cura). Initial PLA profile:
  - Layer: 0.2 mm, Walls: 3, Infill: 10–20% (gyroid or grid).
  - Cards: print text up; no supports.
  - Rod: print horizontal; no supports.

3) Send to Printer
- Create venv and activate:
  - `cd maker && make venv && source .venv/bin/activate`
- OctoPrint upload+print:
  - `export OCTO_KEY=...`
  - `python print/send_to_printer.py --type octoprint --url http://octopi.local --api-key $OCTO_KEY --file tp_rod/tp_rod_170mm_d24mm.gcode --print`
- Moonraker upload+print:
  - `python print/send_to_printer.py --type moonraker --url http://printer.local --file tp_rod/tp_rod_170mm_d24mm.gcode --print`

4) Fit Checks
- 1/2 oz card (Maple): start with 25.2 mm (PLA) or 25.4 mm (PETG).
- If using capsules, measure capsule OD and set target to OD + 0.2–0.4 mm.
- Regenerate: `python card/gen_snug_variants.py` (edit diameters in script if needed).

Open Items
- Confirm Anycubic model + nozzle size (to refine slicing).
- Decide if rod Ø24 mm fits holder sockets; adjust with `--diameter` if needed.
- Optional: push `maker` to a remote repo.
