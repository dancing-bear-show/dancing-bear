"""Budget scoring and safe-coerce helpers extracted from _menubar_app.py."""
from __future__ import annotations


def _budget_score(spend_mtd: float, monthly_budget: float) -> int:
    """Map month-to-date spend vs budget onto a 1–10 scale."""
    if monthly_budget <= 0:
        return 1
    return max(1, min(10, round(spend_mtd / monthly_budget * 10)))


def _safe_float(value: object, default: float) -> float:
    """Coerce arbitrary JSON-decoded values to float; fall back to default."""
    if isinstance(value, bool):
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int) -> int:
    """Coerce arbitrary JSON-decoded values to int; fall back to default."""
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _to_int(v: object) -> int:
    """Convert a JSON/OTLP value to int preserving both precision cases.

    Two correct-but-opposite requirements drove this form:
    - 19-digit nanosecond timestamps must be exact: int(float(1705320000123456789))
      loses 21ns due to float's ~15 decimal digits of precision. An int passthrough
      avoids that.
    - Float values like 123.0 must round-trip: int("123.0") raises ValueError, so
      the float path is needed for non-integer numeric types.
    Neither int(str(v)) nor int(float(v)) alone handles both cases correctly.
    """
    if isinstance(v, int) and not isinstance(v, bool):
        return v                    # exact: avoids float precision loss on ns timestamps
    if isinstance(v, float):
        return int(v)               # tolerant: handles 123.0 -> 123
    try:
        return int(float(str(v)))   # strings: handles "123.0" and "456"
    except (TypeError, ValueError):
        return 0
