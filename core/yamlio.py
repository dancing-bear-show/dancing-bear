"""Shared YAML read/write helpers for personal assistant CLIs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["load_config", "dump_config", "load_config_list"]


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


def load_config_list(
    config: dict,
    key: str,
    *,
    allow_missing: bool = False,
    error_hint: str = ""
) -> List[dict]:
    """Load and validate a list of dicts from config by key.

    Args:
        config: Configuration dictionary
        key: Key to extract list from
        allow_missing: If True, return empty list when key is missing
        error_hint: Error message hint for validation failures

    Returns:
        List of dictionaries

    Raises:
        ValueError: If key is missing (and not allow_missing) or value is not a list of dicts

    Example:
        config = {"labels": [{"name": "inbox"}, {"name": "sent"}]}
        labels = load_config_list(config, "labels", error_hint="labels config")
    """
    data = config.get(key)

    if data is None:
        if allow_missing:
            return []
        hint = f" ({error_hint})" if error_hint else ""
        raise ValueError(f"Missing required key '{key}'{hint}")

    if not isinstance(data, list):
        hint = f" ({error_hint})" if error_hint else ""
        raise ValueError(f"Key '{key}' must be a list{hint}")

    # Filter to only dict entries
    result = [entry for entry in data if isinstance(entry, dict)]

    if len(result) != len(data):
        hint = f" ({error_hint})" if error_hint else ""
        print(f"Warning: Skipped non-dict entries in '{key}'{hint}")

    return result
