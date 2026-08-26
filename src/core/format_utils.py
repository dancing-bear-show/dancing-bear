"""Shared number-formatting helpers used across telemetry and diagrams CLIs."""
from __future__ import annotations

__all__ = ["format_tokens"]


def format_tokens(n: int) -> str:
    """Return a compact human-readable representation of a token count.

    Uses round-half-to-even (banker's rounding) via Python's built-in
    f-string ``:.0f`` formatting.  The 999_500 threshold is intentional:
    at that point the K value rounds to 1000K, so the number rolls over
    to the M tier instead of emitting four K digits.
    """
    # Compare against the M threshold *after* rounding: 999_500 rounds to
    # 1000K, which should roll over to 1.0M rather than render four K digits.
    if n >= 999_500:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)
