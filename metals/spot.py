"""
Daily spot series for precious metals with USD->CAD conversion.

Fetches daily closes for a USD metal ticker (e.g., XAGUSD=X for silver), the
USD/CAD FX rate (USDCAD=X), multiplies them to produce a CAD series, and writes
to CSV. If --start-date is omitted, attempts to auto-detect from local
summaries under out/metals/ (prefers <metal>_summary.csv, else costs.csv).

Usage examples:
  # Silver spot CAD since first purchase → CSV
  python -m metals.spot \
    --metal silver --out out/metals/silver_spot_cad_daily.csv

  # Explicit window
  python -m metals.spot \
    --metal silver --start-date 2025-04-23 --end-date 2025-10-20 \
    --out out/metals/silver_spot_cad_daily.csv

Notes:
  - Uses Yahoo Finance chart API (no auth) for XAGUSD=X and USDCAD=X.
  - Fills missing days by forward-fill; back-fills the beginning to the first
    available value, so downstream charts have a continuous series.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.constants import DEFAULT_REQUEST_TIMEOUT

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


def _parse_yahoo_response(data: Dict) -> Dict[str, float]:
    """Extract date->close mapping from Yahoo Finance JSON response."""
    out: Dict[str, float] = {}
    try:
        res = ((data.get("chart") or {}).get("result") or [])[0]
        ts = res.get("timestamp", [])
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close", [])
        for i, t in enumerate(ts or []):
            try:
                d = datetime.fromtimestamp(int(t), tz=timezone.utc).date().isoformat()
                v = cl[i]
                if v is not None:
                    out[d] = float(v)
            except Exception:  # nosec B112 - skip malformed entries
                continue
    except Exception:  # nosec B110 - return empty on unexpected shape
        pass
    return out


def _fill_date_gaps(data: Dict[str, float], start_date: str, end_date: str) -> Dict[str, float]:
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
        if ds in data:
            last_val = data[ds]
            filled[ds] = last_val
        elif last_val is not None:
            filled[ds] = last_val
        elif first_val is not None:
            filled[ds] = first_val
            last_val = first_val
        dcur = dcur.fromordinal(dcur.toordinal() + 1)

    return filled


def _fetch_yahoo_series(symbol: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch daily closes from Yahoo chart API between inclusive dates (YYYY-MM-DD).

    Returns dict of ISO date -> close. Forward-fills gaps and back-fills the
    initial window to the first available value so a continuous series is
    produced.
    """
    p1 = _to_unix_timestamp(start_date)
    p2 = _to_unix_timestamp(end_date) + 24 * 3600  # period2 is exclusive on Yahoo
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
    headers = {"User-Agent": _YAHOO_USER_AGENT}

    data = _http_get_with_retry(url, headers)
    raw = _parse_yahoo_response(data)
    return _fill_date_gaps(raw, start_date, end_date)


def _parse_stooq_csv(text: str) -> Dict[str, float]:
    """Parse Stooq CSV response into date->close mapping.

    Expected format: Date,Open,High,Low,Close (header + data rows).
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].lower().startswith("date,"):
        return {}

    out: Dict[str, float] = {}
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        date_str = parts[0]
        try:
            close = float(parts[4])
            out[date_str] = close
        except Exception:  # nosec B112 - skip malformed rows
            continue
    return out


def _fetch_stooq_series(symbol: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch daily closes from Stooq CSV endpoint and slice to window.

    symbol examples: 'xagusd' (silver spot USD), 'usdcad' (FX).
    Returns dict date->close with forward/back-fill over the requested window.
    """
    import requests  # lazy import

    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
    try:
        r = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
        if r.status_code >= 400:
            return {}
        text = r.text or ""
    except Exception:  # nosec B110 - return empty on fetch error
        return {}

    raw = _parse_stooq_csv(text)
    return _fill_date_gaps(raw, start_date, end_date)


def _parse_date_safe(date_str: str) -> Optional[date]:
    """Parse ISO date string, returning None on error."""
    try:
        return date.fromisoformat(date_str.strip())
    except Exception:  # nosec B110 - return None on parse error
        return None


def _should_skip_row(row: Dict[str, str], fieldnames: List[str], metal_filter: Optional[str]) -> bool:
    """Check if CSV row should be skipped based on metal filter."""
    if not metal_filter or "metal" not in fieldnames:
        return False

    row_metal = (row.get("metal") or "").strip().lower()
    return row_metal != "" and row_metal != metal_filter


def _find_earliest_date_in_csv(csv_path: Path, metal_filter: Optional[str] = None) -> Optional[date]:
    """Read CSV and find earliest date, optionally filtering by metal column.

    Args:
        csv_path: Path to CSV file with 'date' column
        metal_filter: If provided and 'metal' column exists, filter rows by this value

    Returns:
        Earliest date found or None
    """
    if not csv_path.exists():
        return None

    earliest: Optional[date] = None
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if _should_skip_row(row, reader.fieldnames or [], metal_filter):
                    continue

                d = _parse_date_safe(row.get("date") or "")
                if d and (earliest is None or d < earliest):
                    earliest = d
    except Exception:  # nosec B110 - return None on read error
        pass

    return earliest


def _auto_start_date(metal: str) -> Optional[str]:
    """Find earliest purchase date from out/metals/* CSVs.

    Prefers out/metals/<metal>_summary.csv; falls back to out/metals/costs.csv.
    Returns YYYY-MM-DD or None if unavailable.
    """
    m = (metal or "").strip().lower()
    paths_try: List[Path] = []
    if m in ("silver", "gold"):
        paths_try.append(Path(f"out/metals/{m}_summary.csv"))
    paths_try.append(Path("out/metals/costs.csv"))

    for p in paths_try:
        earliest = _find_earliest_date_in_csv(p, metal_filter=m)
        if earliest:
            return earliest.isoformat()

    return None


def _today_iso() -> str:
    return datetime.now().date().isoformat()


def _get_symbols_for_metal(metal: str) -> tuple[str, str, str, str]:
    """Get (stooq_metal, stooq_fx, yahoo_metal, yahoo_fx) symbols for a metal.

    Args:
        metal: 'silver' or 'gold'

    Returns:
        Tuple of (stooq_metal_symbol, stooq_fx_symbol, yahoo_metal_symbol, yahoo_fx_symbol)
    """
    if metal == "silver":
        return ("xagusd", "usdcad", "XAGUSD=X", "USDCAD=X")
    else:  # gold
        return ("xauusd", "usdcad", "XAUUSD=X", "USDCAD=X")


def _fetch_series_with_fallback(
    metal: str, start_date: str, end_date: str
) -> tuple[Dict[str, float], Dict[str, float]]:
    """Fetch USD metal prices and USD/CAD FX, with Stooq->Yahoo fallback.

    Returns:
        Tuple of (usd_series, fx_series) as date->value dicts
    """
    stooq_metal, stooq_fx, yahoo_metal, yahoo_fx = _get_symbols_for_metal(metal)

    # Prefer Stooq (reliable CSV, no auth)
    usd = _fetch_stooq_series(stooq_metal, start_date, end_date)
    fx = _fetch_stooq_series(stooq_fx, start_date, end_date)

    # Fall back to Yahoo if Stooq failed
    if not usd or not fx:
        usd = _fetch_yahoo_series(yahoo_metal, start_date, end_date)
        fx = _fetch_yahoo_series(yahoo_fx, start_date, end_date)

    return usd, fx


def _build_csv_rows(
    metal: str, usd_series: Dict[str, float], fx_series: Dict[str, float], start_date: str, end_date: str
) -> List[List[str]]:
    """Build CSV rows from USD metal prices and FX rates.

    Args:
        metal: Metal name for column headers
        usd_series: Date->USD price mapping
        fx_series: Date->USDCAD rate mapping
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        List of CSV rows including header
    """
    rows: List[List[str]] = [["date", f"{metal}_usd", "usdcad", f"{metal}_cad"]]
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dcur = start

    while dcur <= end:
        ds = dcur.isoformat()
        u = usd_series.get(ds)
        x = fx_series.get(ds)
        cad = (u * x) if (u is not None and x is not None) else None

        rows.append([
            ds,
            f"{u:.4f}" if u is not None else "",
            f"{x:.6f}" if x is not None else "",
            f"{cad:.4f}" if cad is not None else "",
        ])
        dcur = dcur.fromordinal(dcur.toordinal() + 1)

    return rows


def run(metal: str, start_date: Optional[str], end_date: Optional[str], out_path: str) -> int:
    m = (metal or "").strip().lower()
    if m not in ("silver", "gold"):
        raise SystemExit("--metal must be 'silver' or 'gold'")

    # Determine window
    sdate = start_date or _auto_start_date(m) or (date.today() - timedelta(days=365)).isoformat()
    edate = end_date or _today_iso()

    # Fetch data with fallback
    usd, fx = _fetch_series_with_fallback(m, sdate, edate)

    # Build CSV rows
    rows = _build_csv_rows(m, usd, fx, sdate, edate)

    # Write CSV
    op = Path(out_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    with op.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)
    print(f"wrote {op} rows={len(rows)-1} window={sdate}..{edate}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch daily metal spot in CAD via USD*USDCAD and write CSV")
    p.add_argument("--metal", default="silver", choices=["silver", "gold"], help="Metal to fetch (default: silver)")
    p.add_argument("--start-date", help="YYYY-MM-DD; default: earliest purchase auto-detected or 1y ago")
    p.add_argument("--end-date", help="YYYY-MM-DD; default: today")
    p.add_argument("--out", help="Output CSV path; default: out/metals/<metal>_spot_cad_daily.csv")
    args = p.parse_args(argv)
    metal = getattr(args, "metal", "silver")
    out_default = f"out/metals/{metal}_spot_cad_daily.csv"
    out_path = getattr(args, "out", None) or out_default
    return run(
        metal=metal,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None),
        out_path=out_path,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
