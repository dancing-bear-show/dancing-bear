"""Device I/O helpers for iOS via cfgutil (Apple Configurator).

Also includes credential and certificate utilities for supervision identity management.
"""

from __future__ import annotations

import configparser
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any, Dict, List, Optional, Tuple

from .layout import normalize_iconstate, to_yaml_export


def find_cfgutil_path() -> str:
    """Find cfgutil executable path.

    Raises:
        FileNotFoundError: If cfgutil is not found.
    """
    p = which("cfgutil")
    if p:
        return p
    alt = "/Applications/Apple Configurator.app/Contents/MacOS/cfgutil"
    if Path(alt).exists():
        return alt
    raise FileNotFoundError("cfgutil not found; install Apple Configurator or add cfgutil to PATH")


def map_udid_to_ecid(cfgutil: str, udid: str) -> str:
    """Map a device UDID to its ECID via cfgutil list."""
    try:
        out = subprocess.check_output([cfgutil, "list"], stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        raise RuntimeError(f"cfgutil list failed: {e}")
    for line in out.splitlines():
        if "UDID:" in line and udid in line:
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok.startswith("ECID:"):
                    if tok == "ECID:":
                        if i + 1 < len(parts):
                            return parts[i + 1]
                    else:
                        return tok.split(":", 1)[1]
    return ""


def export_from_device(cfgutil: str, ecid: Optional[str] = None) -> Dict[str, Any]:
    """Export layout from device via cfgutil get-icon-layout."""
    import json as _json
    import plistlib as _plist

    cmd = [cfgutil]
    if ecid:
        cmd.extend(["--ecid", ecid])
    cmd.extend(["--format", "plist", "get-icon-layout"])

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    except Exception as e:
        raise RuntimeError(f"cfgutil get-icon-layout failed: {e}")

    try:
        data = _plist.loads(out)
    except Exception:
        data = None

    if data is None:
        try:
            data = _json.loads(out.decode("utf-8", errors="replace"))
        except Exception as e:
            raise RuntimeError(f"Failed to parse plist or JSON from cfgutil: {e}")

    # Try to convert into our export shape via normalize_iconstate if compatible
    export: Dict[str, Any] = {}
    try:
        layout = normalize_iconstate(data)
        export = to_yaml_export(layout)
    except Exception:
        # Best-effort fallback: attempt to map common keys
        export = _fallback_parse(data)

    return export


def _fallback_parse(data: Any) -> Dict[str, Any]:
    """Fallback parsing for cfgutil output when normalize_iconstate fails."""
    dock: List[str] = []
    pages: List[Dict[str, Any]] = []

    try:
        # cfgutil may return a JSON list: [dock, page1, page2, ...]
        if isinstance(data, list) and data:
            dock = [s for s in (data[0] or []) if isinstance(s, str)]
            for page in data[1:]:
                if not isinstance(page, list):
                    continue
                page_out: Dict[str, Any] = {"apps": [], "folders": []}
                for it in page:
                    if isinstance(it, list) and it:
                        name = it[0] if isinstance(it[0], str) else "Folder"
                        fapps: List[str] = []
                        for sub in it[1:]:
                            if isinstance(sub, list):
                                fapps.extend([s for s in sub if isinstance(s, str)])
                            elif isinstance(sub, str):
                                fapps.append(sub)
                        if fapps:
                            page_out["folders"].append({"name": name or "Folder", "apps": fapps})
                    elif isinstance(it, str):
                        page_out["apps"].append(it)
                pages.append(page_out)
            return {"dock": dock, "pages": pages}

        # Some cfgutil plists carry similar keys as backups
        for it in (data.get("buttonBar") or []):
            bid = it.get("bundleIdentifier") or it.get("displayIdentifier")
            if bid:
                dock.append(bid)
        for page in (data.get("iconLists") or []):
            page_out = {"apps": [], "folders": []}
            for it in (page or []):
                if isinstance(it, dict) and ("iconLists" in it) and ("displayName" in it):
                    name = it.get("displayName") or "Folder"
                    flist: List[str] = []
                    for sub in (it.get("iconLists") or [[]])[0]:
                        bid = sub.get("bundleIdentifier") or sub.get("displayIdentifier")
                        if bid:
                            flist.append(bid)
                    page_out["folders"].append({"name": name, "apps": flist})
                else:
                    bid = it.get("bundleIdentifier") or it.get("displayIdentifier") if isinstance(it, dict) else None
                    if bid:
                        page_out["apps"].append(bid)
            pages.append(page_out)
        return {"dock": dock, "pages": pages}
    except Exception:
        return {}
