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

from core.constants import credential_ini_paths

from .constants import P12_PASS_KEYS, P12_PATH_KEYS
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


def _extract_ecid_from_parts(parts: List[str]) -> str:
    """Extract ECID value from line parts."""
    for i, tok in enumerate(parts):
        if not tok.startswith("ECID:"):
            continue
        # Handle "ECID:value" or "ECID: value" explicitly
        ecid_part = tok.split(":", 1)[1]
        if ecid_part:
            return ecid_part
        if i + 1 < len(parts):
            return parts[i + 1]
        return ""
    return ""


def map_udid_to_ecid(cfgutil: str, udid: str) -> str:
    """Map a device UDID to its ECID via cfgutil list."""
    try:
        out = subprocess.check_output([cfgutil, "list"], stderr=subprocess.STDOUT, text=True)  # nosec B603 - cfgutil from find_cfgutil_path()
    except Exception as e:
        raise RuntimeError(f"cfgutil list failed: {e}")
    for line in out.splitlines():
        if "UDID:" not in line or udid not in line:
            continue
        return _extract_ecid_from_parts(line.split())
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
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)  # nosec B603 - cmd built from trusted literals
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


def _get_bundle_id(item: Any) -> Optional[str]:
    """Extract bundle identifier from a dict item."""
    if not isinstance(item, dict):
        return None
    return item.get("bundleIdentifier") or item.get("displayIdentifier")


def _extract_folder_apps(folder_items: List[Any]) -> List[str]:
    """Extract app list from folder items."""
    apps = []
    for sub in folder_items[1:]:
        if isinstance(sub, str):
            apps.append(sub)
        elif isinstance(sub, list):
            apps.extend(s for s in sub if isinstance(s, str))
    return apps


def _parse_page_item(it: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Parse a single page item into app or folder.

    Returns (app_id, folder_dict) where one will be None.
    """
    if isinstance(it, str):
        return it, None

    if isinstance(it, list) and it:
        name = it[0] if isinstance(it[0], str) else "Folder"
        apps = _extract_folder_apps(it)
        if apps:
            return None, {"name": name or "Folder", "apps": apps}

    return None, None


def _parse_list_format(data: List) -> Dict[str, Any]:
    """Parse cfgutil JSON list format: [dock, page1, page2, ...]."""
    dock = [s for s in (data[0] or []) if isinstance(s, str)]
    pages: List[Dict[str, Any]] = []

    for page in data[1:]:
        if not isinstance(page, list):
            continue
        page_out: Dict[str, Any] = {"apps": [], "folders": []}

        for it in page:
            app_id, folder = _parse_page_item(it)
            if app_id:
                page_out["apps"].append(app_id)
            elif folder:
                page_out["folders"].append(folder)

        pages.append(page_out)

    return {"dock": dock, "pages": pages}


def _parse_plist_format(data: Dict) -> Dict[str, Any]:
    """Parse cfgutil plist format with buttonBar/iconLists keys."""
    dock = [bid for it in (data.get("buttonBar") or []) if (bid := _get_bundle_id(it))]
    pages: List[Dict[str, Any]] = []
    for page in (data.get("iconLists") or []):
        page_out: Dict[str, Any] = {"apps": [], "folders": []}
        for it in (page or []):
            if isinstance(it, dict) and "iconLists" in it and "displayName" in it:
                name = it.get("displayName") or "Folder"
                flist = [bid for sub in (it.get("iconLists") or [[]])[0] if (bid := _get_bundle_id(sub))]
                page_out["folders"].append({"name": name, "apps": flist})
            elif bid := _get_bundle_id(it):
                page_out["apps"].append(bid)
        pages.append(page_out)
    return {"dock": dock, "pages": pages}


def _fallback_parse(data: Any) -> Dict[str, Any]:
    """Fallback parsing for cfgutil output when normalize_iconstate fails."""
    try:
        if isinstance(data, list) and data:
            return _parse_list_format(data)
        if isinstance(data, dict):
            return _parse_plist_format(data)
    except Exception:  # nosec B110 - graceful fallback to empty dict
        pass
    return {}


# -----------------------------------------------------------------------------
# Credentials and certificate helpers
# -----------------------------------------------------------------------------


def read_credentials_ini(explicit: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Dict[str, str]]]:
    """Read credentials.ini and return (path, sections_dict)."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(credential_ini_paths())

    for path in candidates:
        if path and os.path.exists(path):
            cp = configparser.ConfigParser()
            cp.read(path)
            data = {s: dict(cp.items(s)) for s in cp.sections()}
            return path, data

    return None, {}


def _first_value(section: Dict[str, str], keys: Tuple[str, ...]) -> Optional[str]:
    """Return first non-empty value from section for given keys."""
    for key in keys:
        if val := section.get(key):
            return val
    return None


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
        p12_path = _first_value(sec, P12_PATH_KEYS)
        p12_pass = p12_pass or _first_value(sec, P12_PASS_KEYS)

    if p12_path:
        p12_path = os.path.expanduser(p12_path)

    return p12_path, p12_pass


@dataclass
class CertInfo:
    """Certificate information extracted from a .p12 file."""

    subject: str
    issuer: str


def _extract_cert_pem(p12_path: str, p12_pass: Optional[str]) -> bytes:
    """Extract certificate PEM from p12 file, trying legacy mode first."""
    for use_legacy in [True, False]:
        try:
            cmd = ["openssl", "pkcs12"]  # nosec B607
            if use_legacy:
                cmd.append("-legacy")
            cmd.extend(["-in", p12_path, "-clcerts", "-nokeys"])
            if p12_pass:
                cmd.extend(["-passin", f"pass:{p12_pass}"])
            return subprocess.check_output(cmd, stderr=subprocess.DEVNULL)  # nosec B603 - cmd built from trusted literals
        except Exception:  # nosec B112 - try legacy/non-legacy openssl modes
            continue
    raise RuntimeError(f"Failed to extract certificate from {p12_path}")


def _x509_field(cert_pem: bytes, field: str) -> str:
    """Extract a field (subject/issuer) from certificate PEM."""
    try:
        out = subprocess.check_output(  # nosec B603 B607 - openssl in PATH, field from trusted caller
            ["openssl", "x509", "-noout", f"-{field}"],
            input=cert_pem,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip().replace(f"{field}=", "")
    except Exception:  # nosec B110 - cert parsing failure
        return ""


def extract_p12_cert_info(p12_path: str, p12_pass: Optional[str] = None) -> CertInfo:
    """Extract certificate subject and issuer from a .p12 file using openssl.

    Raises:
        FileNotFoundError: If p12 file doesn't exist.
        RuntimeError: If openssl extraction fails.
    """
    if not os.path.exists(p12_path):
        raise FileNotFoundError(f"p12 file not found: {p12_path}")

    cert_pem = _extract_cert_pem(p12_path, p12_pass)
    return CertInfo(
        subject=_x509_field(cert_pem, "subject"),
        issuer=_x509_field(cert_pem, "issuer"),
    )


def get_device_supervision_status(cfgutil_path: Optional[str] = None) -> Optional[str]:
    """Query device supervision status via cfgutil.

    Returns the supervision status string, or None if unavailable.
    """
    try:
        cfg = cfgutil_path or find_cfgutil_path()
    except FileNotFoundError:
        return None

    try:
        out = subprocess.check_output([cfg, "get", "Supervised"], stderr=subprocess.DEVNULL, text=True)  # nosec B603 - cfg from find_cfgutil_path()
        if "Supervised:" in out:
            return out.split(":", 1)[1].strip()
    except Exception:  # nosec B110 - cfgutil query failure
        pass

    return None


def resolve_udid_from_label(
    label: str, cfg_path: Optional[str], _ini: Dict[str, Dict[str, str]]
) -> Optional[str]:
    """Resolve device UDID from a label using credentials.ini [ios_devices] section."""
    if not label or not cfg_path or not os.path.exists(cfg_path):
        return None

    cp = configparser.ConfigParser()
    cp.read(cfg_path)
    if cp.has_section("ios_devices") and cp.has_option("ios_devices", label):
        return cp.get("ios_devices", label)

    return None
