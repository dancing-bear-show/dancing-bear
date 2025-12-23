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


# -----------------------------------------------------------------------------
# Credentials and certificate helpers
# -----------------------------------------------------------------------------

_CREDENTIALS_PATHS = [
    "{xdg}/credentials.ini",
    "~/.config/credentials.ini",
    "{xdg}/sre-utils/credentials.ini",
    "~/.config/sre-utils/credentials.ini",
    "~/.config/sreutils/credentials.ini",
    "~/.sre-utils/credentials.ini",
]


def read_credentials_ini(explicit: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Dict[str, str]]]:
    """Read credentials.ini and return (path, sections_dict)."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("CREDENTIALS"):
        candidates.append(os.environ["CREDENTIALS"])

    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    for template in _CREDENTIALS_PATHS:
        candidates.append(template.format(xdg=xdg).replace("~", os.path.expanduser("~")))

    for path in candidates:
        if path and os.path.exists(path):
            cp = configparser.ConfigParser()
            cp.read(path)
            data = {s: dict(cp.items(s)) for s in cp.sections()}
            return path, data

    return None, {}


def resolve_p12_path(
    explicit_path: Optional[str],
    explicit_pass: Optional[str],
    creds_profile: str,
    ini: Dict[str, Dict[str, str]],
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve p12 path and password from args or credentials.ini."""
    p12_path = explicit_path
    p12_pass = explicit_pass

    if not p12_path and creds_profile in ini:
        sec = ini[creds_profile]
        p12_path = (
            sec.get("supervision_identity_p12")
            or sec.get("ios_home_layout_identity_p12")
            or sec.get("supervision_p12")
        )
        p12_pass = p12_pass or (
            sec.get("supervision_identity_pass")
            or sec.get("ios_home_layout_identity_pass")
            or sec.get("supervision_p12_pass")
        )

    # Expand ~
    if p12_path and p12_path.startswith("~/"):
        p12_path = os.path.expanduser(p12_path)

    return p12_path, p12_pass


@dataclass
class CertInfo:
    """Certificate information extracted from a .p12 file."""

    subject: str
    issuer: str


def extract_p12_cert_info(p12_path: str, p12_pass: Optional[str] = None) -> CertInfo:
    """Extract certificate subject and issuer from a .p12 file using openssl.

    Raises:
        FileNotFoundError: If p12 file doesn't exist.
        RuntimeError: If openssl extraction fails.
    """
    if not os.path.exists(p12_path):
        raise FileNotFoundError(f"p12 file not found: {p12_path}")

    # Try with -legacy flag first (OpenSSL 3.x), then without
    cert_pem = None
    for use_legacy in [True, False]:
        try:
            cmd = ["openssl", "pkcs12"]
            if use_legacy:
                cmd.append("-legacy")
            cmd.extend(["-in", p12_path, "-clcerts", "-nokeys"])
            if p12_pass:
                cmd.extend(["-passin", f"pass:{p12_pass}"])
            cert_pem = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            break
        except Exception:
            continue

    if cert_pem is None:
        raise RuntimeError(f"Failed to extract certificate from {p12_path}")

    # Extract subject and issuer
    subject = ""
    issuer = ""
    try:
        subj_out = subprocess.check_output(
            ["openssl", "x509", "-noout", "-subject"],
            input=cert_pem,
            stderr=subprocess.DEVNULL,
        )
        subject = subj_out.decode().strip().replace("subject=", "")
    except Exception:
        pass

    try:
        iss_out = subprocess.check_output(
            ["openssl", "x509", "-noout", "-issuer"],
            input=cert_pem,
            stderr=subprocess.DEVNULL,
        )
        issuer = iss_out.decode().strip().replace("issuer=", "")
    except Exception:
        pass

    return CertInfo(subject=subject, issuer=issuer)


def get_device_supervision_status(cfgutil_path: Optional[str] = None) -> Optional[str]:
    """Query device supervision status via cfgutil.

    Returns the supervision status string, or None if unavailable.
    """
    try:
        cfg = cfgutil_path or find_cfgutil_path()
    except FileNotFoundError:
        return None

    try:
        out = subprocess.check_output([cfg, "get", "Supervised"], stderr=subprocess.DEVNULL, text=True)
        if "Supervised:" in out:
            return out.split(":", 1)[1].strip()
    except Exception:
        pass

    return None


def resolve_udid_from_label(
    label: str, cfg_path: Optional[str], ini: Dict[str, Dict[str, str]]
) -> Optional[str]:
    """Resolve device UDID from a label using credentials.ini [ios_devices] section."""
    if not label or not cfg_path or not os.path.exists(cfg_path):
        return None

    cp = configparser.ConfigParser()
    cp.read(cfg_path)
    if cp.has_section("ios_devices") and cp.has_option("ios_devices", label):
        return cp.get("ios_devices", label)

    return None
