"""Shared YAML read/write helpers for personal assistant CLIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.cli_errors import CLIError, ExitCode

__all__ = ["dump_config", "dump_yaml_text", "load_config"]


def _require_yaml():
    try:
        import yaml

        return yaml
    except Exception as exc:  # pragma: no cover - runtime guard
        raise CLIError(
            "PyYAML not installed. Run: pip install pyyaml", ExitCode.CONFIG_ERROR
        ) from exc


def load_config(path: str | None) -> dict[str, Any]:
    """Load a YAML file into a dict; returns {} if missing/empty."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    yaml = _require_yaml()
    result = yaml.safe_load(text)
    # None means empty/comment-only YAML; coerce to empty dict
    if result is None:
        result = {}
    return result


def dump_yaml_text(data: Any, *, sort_keys: bool = False) -> str:
    """Serialize ``data`` to block-style YAML text.

    Uses ``safe_dump`` with ``allow_unicode=True`` so non-ASCII text stays
    readable instead of being escaped. Key order is preserved unless
    ``sort_keys`` is set. Raises ``CLIError`` when PyYAML is not installed.
    """
    yaml = _require_yaml()
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=sort_keys, allow_unicode=True)


def dump_config(path: str, data: dict[str, Any]) -> None:
    """Write a dict to YAML with stable ordering for humans."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump_yaml_text(data), encoding="utf-8")
