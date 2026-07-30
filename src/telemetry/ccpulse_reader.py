"""Reader for ccpulse session insights."""
from __future__ import annotations

import json
import time
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".ccpulse" / "current-tips.json"
_SUPPORTED_SCHEMAS = {1}
_STALE_AFTER_SECONDS = 600


def read_current(
    path: Path | None = None,
    stale_after_seconds: int = _STALE_AFTER_SECONDS,
    now: float | None = None,
) -> dict | None:
    """Return the latest ccpulse payload, or None if unusable."""
    target = path or _DEFAULT_PATH
    try:
        st = target.stat()
    except OSError:
        return None

    age = (now if now is not None else time.time()) - st.st_mtime
    if age > stale_after_seconds:
        return None

    try:
        payload = json.loads(target.read_text())
    except (OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("schema") not in _SUPPORTED_SCHEMAS:
        return None
    if "error" in payload:
        return None

    return payload
