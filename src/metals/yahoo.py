"""Shared parsing helpers for Yahoo Finance chart API responses.

Both the spot-series CLI (``metals.spot``) and the Excel chart builder
(``metals.excel_chart``) fetch daily closes from the same unauthenticated
Yahoo chart endpoint, so the response-shape handling lives here once.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def parse_point(ts: List, closes: List, i: int) -> Optional[Tuple[str, float]]:
    """Parse a single (timestamp, close) pair at index i. Returns None if invalid."""
    try:
        d = datetime.fromtimestamp(int(ts[i]), tz=timezone.utc).date().isoformat()
        v = closes[i]
        if v is None:
            return None
        return d, float(v)
    except Exception:  # nosec B110 - skip malformed entries
        return None


def parse_response(data: Dict) -> Dict[str, float]:
    """Extract date->close mapping from a Yahoo Finance chart JSON response."""
    out: Dict[str, float] = {}
    try:
        res = ((data.get("chart") or {}).get("result") or [])[0]
        ts = res.get("timestamp", []) or []
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close", [])
    except Exception:  # nosec B110 - return empty on unexpected shape
        return out

    for i in range(len(ts)):
        point = parse_point(ts, cl, i)
        if point:
            out[point[0]] = point[1]
    return out
