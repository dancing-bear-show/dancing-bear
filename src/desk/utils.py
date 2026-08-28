from __future__ import annotations

import os
import re
from typing import Iterable

from core.cli_output import emit_one
from core.fileutil import atomic_write_json as _write_json
from core.yamlio import dump_config as _dump_yaml


def expand_paths(paths: Iterable[str]) -> list[str]:
    return [os.path.abspath(os.path.expanduser(p)) for p in paths]


_SIZE_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)?)(?P<unit>[KkMmGgTt][Bb]?)?$")


def parse_size(s: str) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    s = s.strip()
    m = _SIZE_RE.match(s)
    if not m:
        # assume raw bytes
        return int(float(s))
    num = float(m.group("num"))
    unit = m.group("unit")
    if not unit:
        return int(num)
    u = unit[0].lower()
    mult = {
        "k": 1024,
        "m": 1024 ** 2,
        "g": 1024 ** 3,
        "t": 1024 ** 4,
    }[u]
    return int(num * mult)


_DUR_PART = re.compile(r"(?P<num>\d+)(?P<unit>[smhdw])", re.IGNORECASE)


def parse_duration(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip()
    total = 0
    for m in _DUR_PART.finditer(s):
        num = int(m.group("num"))
        unit = m.group("unit").lower()
        mult = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }[unit]
        total += num * mult
    if total == 0 and s.isdigit():
        return int(s)
    return total or None


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{int(n)} TB"


def dump_output(obj: dict, out_path: str | None) -> None:
    if not out_path:
        # default to pretty JSON on stdout
        emit_one(obj)
        return
    out_path = os.path.expanduser(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if out_path.lower().endswith((".yaml", ".yml")):
        _dump_yaml(out_path, obj)
        return
    _write_json(out_path, obj)
