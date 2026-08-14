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
