from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from personal_core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml

from .backup import find_latest_backup_dir, find_iconstate_file, load_plist
from .layout import NormalizedLayout, normalize_iconstate


@dataclass
class LayoutLoadError(Exception):
    code: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - simple formatting
        return self.message


def write_yaml(data: Dict[str, Any], out_path: Path) -> None:
    _dump_yaml(str(out_path), data)


def read_yaml(in_path: Path) -> Dict[str, Any]:
    if not in_path.exists():
        raise FileNotFoundError(in_path)
    data = _load_yaml(str(in_path)) or {}
    return data


def _layout_from_export(export: Dict[str, Any]) -> NormalizedLayout:
    dock = export.get("dock") or []
    pages = []
    for p in export.get("pages") or []:
        items = []
        for a in p.get("apps", []):
            items.append({"kind": "app", "id": a})
        for f in p.get("folders", []):
            items.append({"kind": "folder", "name": f.get("name"), "apps": f.get("apps", [])})
        pages.append(items)
    return NormalizedLayout(dock=dock, pages=pages)


def load_layout(layout_path: Optional[str], backup_path: Optional[str]) -> NormalizedLayout:
    if layout_path:
        export = read_yaml(Path(layout_path).expanduser())
        return _layout_from_export(export)

    backup_dir = Path(backup_path).expanduser() if backup_path else find_latest_backup_dir()
    if not backup_dir or not backup_dir.exists():
        raise LayoutLoadError(2, "Error: No Finder backup found. Provide --backup or create an encrypted backup in Finder.")
    iconfile = find_iconstate_file(backup_dir)
    if not iconfile:
        raise LayoutLoadError(3, f"Error: IconState plist not found in backup at {backup_dir}")
    data = load_plist(iconfile.path)
    return normalize_iconstate(data)


def read_lines_file(path: Optional[str]) -> List[str]:
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    try:
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []
