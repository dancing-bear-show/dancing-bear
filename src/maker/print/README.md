# Network Printing (OctoPrint/Moonraker)

This folder provides a tiny helper to upload and (optionally) start prints on a network-connected 3D printer via OctoPrint or Moonraker.

Status
- Script ready: `print/send_to_printer.py`
- Supports: OctoPrint (API key) and Moonraker (HTTP endpoints)

Prereqs
- You already have OctoPrint (OctoPi on a Raspberry Pi) or Klipper+Moonraker (with Fluidd/Mainsail) connected to your Anycubic via USB.
- You have an API key (OctoPrint) or access to the Moonraker HTTP endpoints.
- You sliced your model to G-code (uploading STL directly is not supported here).

Quick start
- cd maker && make venv && source .venv/bin/activate
- python print/send_to_printer.py --type octoprint --url http://octopi.local \\
  --api-key YOUR_KEY --file tp_rod/tp_rod_170mm_d24mm.gcode --print

Env vars (optional)
- PRINTER_TYPE: octoprint|moonraker
- PRINTER_URL: base URL (e.g., http://octopi.local)
- PRINTER_API_KEY: OctoPrint API key (Moonraker usually not needed)

Examples
- OctoPrint upload + start:
  python print/send_to_printer.py --type octoprint --url http://octopi.local \\
    --api-key $OCTO_KEY --file path/to/model.gcode --print

- Moonraker upload + start:
  python print/send_to_printer.py --type moonraker --url http://printer.local \\
    --file path/to/model.gcode --print

Notes
- Slicing: Use your desktop slicer (PrusaSlicer/Cura/Orca) and export .gcode first.
- Security: Do not commit API keys. Use env vars or your shell history cautiously.
