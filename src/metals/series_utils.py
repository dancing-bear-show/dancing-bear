"""Shared date-series helpers for fetching and gap-filling metal spot prices.

Both the spot-series CLI (``metals.spot``) and the Excel chart builder
(``metals.excel_chart``) fetch daily closes from the same unauthenticated
Yahoo chart endpoint and forward/back-fill the resulting series over a
continuous daily range, so that handling lives here once.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, Optional

from core.constants import DEFAULT_REQUEST_TIMEOUT

from .yahoo import parse_response as _parse_yahoo_response

# HTTP retry constants
_MAX_RETRIES = 6
_INITIAL_BACKOFF = 2
_RETRY_SLEEP_BASE = 1

# User agent for Yahoo Finance requests
_YAHOO_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _to_unix_timestamp(date_str: str) -> int:
    """Convert YYYY-MM-DD to Unix timestamp."""
    dt = datetime.fromisoformat(date_str)
    return int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp())


def _http_get_with_retry(url: str, headers: Optional[Dict[str, str]] = None) -> Dict:
    """Fetch URL with exponential backoff for 429/5xx errors."""
    import requests
    import time as _t

    data = {}
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT, headers=headers)
            if r.status_code == 429 or r.status_code >= 500:
                _t.sleep(_INITIAL_BACKOFF + attempt * 2)
                continue
            data = r.json() or {}
            break
        except Exception:  # nosec B112 - retry on transient errors
            _t.sleep(_RETRY_SLEEP_BASE + attempt)
    return data


def _resolve_gap_fill(
    data: Dict[str, float], ds: str, last_val: Optional[float], first_val: Optional[float]
) -> Optional[float]:
    """Resolve the value to fill in for date ds: exact match, else forward-fill, else back-fill."""
    if ds in data:
        return data[ds]
    if last_val is not None:
        return last_val
    return first_val


def fill_date_gaps(data: Dict[str, float], start_date: str, end_date: str) -> Dict[str, float]:
    """Forward-fill and back-fill gaps to produce continuous daily series.

    For dates before first available data, back-fill with first value.
    For dates after first data with gaps, forward-fill with last known value.
    """
    if not data:
        return data

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    avail_dates = sorted(data.keys())
    first_val = data.get(avail_dates[0]) if avail_dates else None

    filled: Dict[str, float] = {}
    last_val = None
    dcur = start

    while dcur <= end:
        ds = dcur.isoformat()
        val = _resolve_gap_fill(data, ds, last_val, first_val)
        if val is not None:
            filled[ds] = val
            last_val = val
        dcur = dcur.fromordinal(dcur.toordinal() + 1)

    return filled


def fetch_yahoo_series(symbol: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch daily closes from Yahoo chart API between inclusive dates (YYYY-MM-DD).

    Returns dict of ISO date -> close. Forward-fills gaps and back-fills the
    initial window to the first available value so a continuous series is
    produced. Uses retry-with-backoff and a browser User-Agent to reduce
    rate-limiting from the unauthenticated Yahoo endpoint.
    """
    p1 = _to_unix_timestamp(start_date)
    p2 = _to_unix_timestamp(end_date) + 24 * 3600  # period2 is exclusive on Yahoo
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
    headers = {"User-Agent": _YAHOO_USER_AGENT}

    data = _http_get_with_retry(url, headers)
    raw = _parse_yahoo_response(data)
    return fill_date_gaps(raw, start_date, end_date)
