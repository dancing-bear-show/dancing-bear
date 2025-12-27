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


def _fetch_yahoo_series(symbol: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch daily closes from Yahoo chart API between inclusive dates (YYYY-MM-DD).

    Returns dict of ISO date -> close. Forward-fills gaps and back-fills the
    initial window to the first available value so a continuous series is
    produced.
    """
    import requests  # lazy import

    def to_unix(d: str) -> int:
        dt = datetime.fromisoformat(d)
        return int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp())

    p1 = to_unix(start_date)
    # period2 is exclusive on Yahoo; add one day to include end_date
    p2 = to_unix(end_date) + 24 * 3600
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
    # Simple retry with backoff for transient rate limits (HTTP 429) or 5xx
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
    data = {}
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT, headers=headers)
            if r.status_code == 429 or r.status_code >= 500:
                import time as _t
                _t.sleep(2 + attempt * 2)
                continue
            data = r.json() or {}
            break
        except Exception:
            import time as _t
            _t.sleep(1 + attempt)
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
            except Exception:  # noqa: S112 - skip on error
                continue
    except Exception:
        # If shape unexpected, return empty
        return out

    # Forward-fill and back-fill to cover all days in window
    if out:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        dcur = start
        # Identify first available data point for back-fill
        avail_dates = sorted(out.keys())
        first_val = out.get(avail_dates[0]) if avail_dates else None
        last = None
        while dcur <= end:
            ds = dcur.isoformat()
            if ds in out:
                last = out[ds]
            elif last is not None:
                out[ds] = last
            elif first_val is not None:
                out[ds] = first_val
                last = first_val
            dcur = dcur.fromordinal(dcur.toordinal() + 1)
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
    except Exception:
        return {}

    # Parse CSV lines: Date,Open,High,Low,Close
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].lower().startswith("date,"):
        return {}
    out_raw: Dict[str, float] = {}
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        ds = parts[0]
        try:
            close = float(parts[4])
        except Exception:  # noqa: S112 - skip on error
            continue
        out_raw[ds] = close

    # Create windowed, forward/back-filled series
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    values: Dict[str, float] = {}
    # Determine first available value for back-fill
    first_ds = min(out_raw.keys()) if out_raw else None
    first_val = out_raw.get(first_ds) if first_ds else None
    last_val = None
    dcur = start
    while dcur <= end:
        ds = dcur.isoformat()
        if ds in out_raw:
            last_val = out_raw[ds]
            values[ds] = last_val
        elif last_val is not None:
            values[ds] = last_val
        elif first_val is not None:
            values[ds] = first_val
            last_val = first_val
        dcur = dcur.fromordinal(dcur.toordinal() + 1)
    return values


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

    def parse_date(s: str) -> Optional[date]:
        try:
            return date.fromisoformat(s.strip())
        except Exception:
            return None

    earliest: Optional[date] = None
    for p in paths_try:
        if not p.exists():
            continue
        try:
            with p.open(newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    if m and "metal" in r.fieldnames or []:
                        # If costs.csv, filter by metal
                        metal_row = (row.get("metal") or "").strip().lower()
                        if metal_row and metal_row != m:
                            continue
                    d = parse_date(row.get("date") or "")
                    if d is None:
                        continue
                    if earliest is None or d < earliest:
                        earliest = d
        except Exception:  # noqa: S112 - skip on error
            continue
        if earliest:
            break
    return earliest.isoformat() if earliest else None


def _today_iso() -> str:
    return datetime.now().date().isoformat()


def run(metal: str, start_date: Optional[str], end_date: Optional[str], out_path: str) -> int:
    m = (metal or "").strip().lower()
    if m not in ("silver", "gold"):
        raise SystemExit("--metal must be 'silver' or 'gold'")

    # Determine window
    sdate = start_date or _auto_start_date(m) or (date.today() - timedelta(days=365)).isoformat()
    edate = end_date or _today_iso()
    # Pick Yahoo symbols (USD and FX)
    sym_usd = "XAGUSD=X" if m == "silver" else "XAUUSD=X"
    sym_fx = "USDCAD=X"  # USD in CAD

    # Prefer Stooq (reliable CSV, no auth); fall back to Yahoo
    usd = _fetch_stooq_series("xagusd" if m == "silver" else "xauusd", sdate, edate)
    fx = _fetch_stooq_series("usdcad", sdate, edate)
    if not usd or not fx:
        usd = _fetch_yahoo_series(sym_usd, sdate, edate)
        fx = _fetch_yahoo_series(sym_fx, sdate, edate)

    # Compose daily rows
    start = date.fromisoformat(sdate)
    end = date.fromisoformat(edate)
    rows: List[List[str]] = [["date", f"{m}_usd", "usdcad", f"{m}_cad"]]
    dcur = start
    while dcur <= end:
        ds = dcur.isoformat()
        u = usd.get(ds)
        x = fx.get(ds)
        cad = (u * x) if (u is not None and x is not None) else None
        rows.append([ds, f"{u:.4f}" if u is not None else "", f"{x:.6f}" if x is not None else "", f"{cad:.4f}" if cad is not None else ""])
        dcur = dcur.fromordinal(dcur.toordinal() + 1)

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
