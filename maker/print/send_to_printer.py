#!/usr/bin/env python3
"""
Upload (and optionally start) a G-code print to OctoPrint or Moonraker.

Usage:
  PRINTER_TYPE=octoprint PRINTER_URL=http://octopi.local PRINTER_API_KEY=... \
  python print/send_to_printer.py --file path/to/model.gcode --print

  python print/send_to_printer.py --type moonraker --url http://printer.local \
    --file path/to/model.gcode --print
"""
import argparse
import os
import sys
import requests
from pathlib import Path


def upload_octoprint(url: str, api_key: str, file: Path, do_print: bool):
    # POST /api/files/local
    headers = {"X-Api-Key": api_key}
    with open(file, "rb") as fh:
        files = {"file": (file.name, fh, "application/octet-stream")}
        data = {"print": "true" if do_print else "false"}
        r = requests.post(f"{url.rstrip('/')}/api/files/local", headers=headers, files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


def upload_moonraker(url: str, file: Path, do_print: bool):
    # POST /server/files/upload
    with open(file, "rb") as fh:
        files = {"file": (file.name, fh, "application/octet-stream")}
        r = requests.post(f"{url.rstrip('/')}/server/files/upload", files=files, timeout=60)
    r.raise_for_status()
    if do_print:
        # Start: POST /printer/print/start {"filename":"gcodes/<name>"}
        # Moonraker usually places uploads under gcodes/
        payload = {"filename": f"gcodes/{file.name}"}
        r2 = requests.post(f"{url.rstrip('/')}/printer/print/start", json=payload, timeout=30)
        r2.raise_for_status()
    return {"status": "ok"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["octoprint", "moonraker"], default=os.getenv("PRINTER_TYPE", "octoprint"))
    ap.add_argument("--url", default=os.getenv("PRINTER_URL"), help="Base URL of printer service")
    ap.add_argument("--api-key", default=os.getenv("PRINTER_API_KEY"), help="OctoPrint API key (if type=octoprint)")
    ap.add_argument("--file", required=True, type=Path, help="Path to .gcode file to upload")
    ap.add_argument("--print", dest="do_print", action="store_true", help="Start printing after upload")
    args = ap.parse_args()

    if not args.url:
        ap.error("--url (or PRINTER_URL) is required")
    if args.type == "octoprint" and not args.api_key:
        ap.error("--api-key (or PRINTER_API_KEY) required for OctoPrint")
    if not args.file.exists():
        ap.error(f"File not found: {args.file}")

    if args.type == "octoprint":
        info = upload_octoprint(args.url, args.api_key, args.file, args.do_print)
    else:
        info = upload_moonraker(args.url, args.file, args.do_print)
    print("Upload complete:", info)


if __name__ == "__main__":
    main()

