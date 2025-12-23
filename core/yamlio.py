"""Shared YAML read/write helpers for personal assistant CLIs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

__all__ = ["load_config", "dump_config"]


def _require_yaml():
    try:
        import yaml  # type: ignore

        return yaml
    except Exception as exc:  # pragma: no cover - runtime guard
        raise RuntimeError("PyYAML not installed. Run: pip install pyyaml") from exc


def load_config(path: Optional[str]) -> Dict[str, Any]:
    """Load a YAML file into a dict; returns {} if missing/empty."""
    if not path:
        return {}
    yaml = _require_yaml()
    p = Path(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    # Keep parity with previous behavior: non-dict roots are returned as-is
    return data  # type: ignore[return-value]


def dump_config(path: str, data: Dict[str, Any]) -> None:
    """Write a dict to YAML with stable ordering for humans."""
    yaml = _require_yaml()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
