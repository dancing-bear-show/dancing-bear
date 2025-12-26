"""
Analyze purchase premium over spot and estimate 'fractional premium'.

Reads costs from out/metals/costs.csv (produced by extract-metals-costs),
fetches daily spot for the metal (USD) and USD/CAD, computes same-day CAD
spot, and then computes per-order premium per ounce and percentage.

Outputs a detailed CSV and prints a summary grouped by unit class:
  - fractional (<1 oz only)
  - one_oz (≈1 oz only)
  - bulk (>1 oz only)
  - mixed (mixture of sizes)

Usage examples:
  python -m metals.premium \
    --metal gold --out out/metals/premium_gold.csv

  python -m metals.premium \
    --metal silver --costs out/metals/costs.csv --out out/metals/premium_silver.csv
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .spot import _fetch_stooq_series, _fetch_yahoo_series


@dataclass
class CostRow:
    date: str
    vendor: str
    metal: str
    currency: str
    cost_per_oz: float
    total_oz: float
    order_id: str
    units_breakdown: str


def _parse_costs(path: str, metal: str) -> List[CostRow]:
    rows: List[CostRow] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            m = (row.get("metal") or "").strip().lower()
            if m != metal:
                continue
            try:
                cpo = float(row.get("cost_per_oz") or 0)
                toz = float(row.get("total_oz") or 0)
            except Exception:  # noqa: S112 - skip on error
                continue
            if cpo <= 0 or toz <= 0:
                continue
            rows.append(
                CostRow(
                    date=(row.get("date") or "").strip(),
                    vendor=(row.get("vendor") or "").strip(),
                    metal=m,
                    currency=(row.get("currency") or "").strip(),
                    cost_per_oz=cpo,
                    total_oz=toz,
                    order_id=(row.get("order_id") or "").strip(),
                    units_breakdown=(row.get("units_breakdown") or "").strip(),
                )
            )
    return rows


def _parse_units_breakdown(s: str) -> List[Tuple[float, float]]:
    """Parse units_breakdown like '0.1ozx2;1ozx3' into list of (unit_oz, qty)."""
    out: List[Tuple[float, float]] = []
    if not s:
        return out
    for tok in s.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        # Expect format '<oz>ozx<qty>'
        try:
            if "ozx" in tok:
                oz_s, q_s = tok.split("ozx", 1)
                oz = float(oz_s)
                qty = float(q_s)
                out.append((oz, qty))
            elif tok.endswith("oz"):
                # Fallback: '<oz>oz'
                oz = float(tok[:-2])
                out.append((oz, 1.0))
        except Exception:  # noqa: S112 - skip on error
            continue
    return out


def _classify_units(units: List[Tuple[float, float]]) -> str:
    if not units:
        return "unknown"
    low = all(u < 0.98 for (u, _q) in units)
    one = all(0.98 <= u <= 1.02 for (u, _q) in units)
    high = all(u > 1.02 for (u, _q) in units)
    if low:
        return "fractional"
    if one:
        return "one_oz"
    if high:
        return "bulk"
    return "mixed"


def _window(rows: List[CostRow]) -> Tuple[str, str]:
    dmin: Optional[str] = None
    dmax: Optional[str] = None
    for r in rows:
        d = (r.date or "").strip()
        if not d:
            continue
        if dmin is None or d < dmin:
            dmin = d
        if dmax is None or d > dmax:
            dmax = d
    if not dmin or not dmax:
        today = date.today().isoformat()
        return today, today
    return dmin, dmax


def _spot_series_cad(metal: str, start_date: str, end_date: str) -> Dict[str, float]:
    m = (metal or "").lower()
    if m not in ("silver", "gold"):
        return {}
    usd = _fetch_stooq_series("xagusd" if m == "silver" else "xauusd", start_date, end_date)
    fx = _fetch_stooq_series("usdcad", start_date, end_date)
    if not usd or not fx:
        usd = _fetch_yahoo_series("XAGUSD=X" if m == "silver" else "XAUUSD=X", start_date, end_date)
        fx = _fetch_yahoo_series("USDCAD=X", start_date, end_date)
    out: Dict[str, float] = {}
    # Multiply element-wise (both series are already daily, forward/back-filled)
    cur = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while cur <= end:
        ds = cur.isoformat()
        u = usd.get(ds)
        x = fx.get(ds)
        if u is not None and x is not None:
            out[ds] = float(u) * float(x)
        cur = cur.fromordinal(cur.toordinal() + 1)
    return out


def run(metal: str, costs_path: str, out_path: str) -> int:
    m = (metal or "").strip().lower()
    if m not in ("silver", "gold"):
        raise SystemExit("--metal must be 'silver' or 'gold'")
    rows = _parse_costs(costs_path, m)
    if not rows:
        print("no matching rows in costs file")
        return 0
    start, end = _window(rows)
    spot = _spot_series_cad(m, start, end)

    # Prepare output rows
    out_rows: List[List[str]] = [[
        "date", "vendor", "order_id", "metal", "unit_class", "units_breakdown",
        "cost_per_oz_cad", "spot_cad", "premium_abs", "premium_pct", "total_oz", "unit_count",
    ]]

    # Aggregation by class
    agg = {
        "fractional": {"sum_oz": 0.0, "sum_prem_abs_x_oz": 0.0, "sum_prem_pct_x_oz": 0.0, "n": 0},
        "one_oz": {"sum_oz": 0.0, "sum_prem_abs_x_oz": 0.0, "sum_prem_pct_x_oz": 0.0, "n": 0},
        "bulk": {"sum_oz": 0.0, "sum_prem_abs_x_oz": 0.0, "sum_prem_pct_x_oz": 0.0, "n": 0},
        "mixed": {"sum_oz": 0.0, "sum_prem_abs_x_oz": 0.0, "sum_prem_pct_x_oz": 0.0, "n": 0},
        "unknown": {"sum_oz": 0.0, "sum_prem_abs_x_oz": 0.0, "sum_prem_pct_x_oz": 0.0, "n": 0},
    }

    for r in rows:
        ds = r.date
        scad = spot.get(ds)
        if scad is None or scad <= 0:
            continue
        units = _parse_units_breakdown(r.units_breakdown)
        cls = _classify_units(units)
        unit_count = sum(q for (_u, q) in units) if units else 0.0
        prem_abs = r.cost_per_oz - scad
        prem_pct = (prem_abs / scad) if scad else 0.0

        out_rows.append([
            ds,
            r.vendor,
            r.order_id,
            r.metal,
            cls,
            r.units_breakdown,
            f"{r.cost_per_oz:.2f}",
            f"{scad:.2f}",
            f"{prem_abs:.2f}",
            f"{prem_pct:.4f}",
            f"{r.total_oz:.3f}",
            f"{int(unit_count) if abs(unit_count - int(unit_count)) < 1e-6 else unit_count}",
        ])

        # Aggregate (ounce-weighted)
        a = agg.get(cls) or agg["unknown"]
        a["sum_oz"] += r.total_oz
        a["sum_prem_abs_x_oz"] += prem_abs * r.total_oz
        a["sum_prem_pct_x_oz"] += prem_pct * r.total_oz
        a["n"] += 1

    # Write detailed CSV
    op = Path(out_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    with op.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(out_rows)
    print(f"wrote {op} rows={len(out_rows)-1}")

    # Print summary
    def fmt_pct(x: float) -> str:
        return f"{x*100:.2f}%"

    print("summary (ounce-weighted):")
    for cls in ("fractional", "one_oz", "bulk", "mixed"):
        a = agg[cls]
        if a["sum_oz"] <= 0:
            continue
        w_avg_abs = a["sum_prem_abs_x_oz"] / a["sum_oz"]
        w_avg_pct = a["sum_prem_pct_x_oz"] / a["sum_oz"]
        print(f"- {cls}: n={a['n']} oz={a['sum_oz']:.2f} avg_prem={w_avg_abs:.2f} CAD/oz ({fmt_pct(w_avg_pct)})")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Compute per-order premium vs spot and summarize fractional premium")
    p.add_argument("--metal", default="silver", choices=["silver", "gold"])  # default: silver
    p.add_argument("--costs", default="out/metals/costs.csv")
    p.add_argument("--out", help="Output CSV path; default: out/metals/premium_<metal>.csv")
    args = p.parse_args(argv)
    metal = getattr(args, "metal", "silver")
    out_default = f"out/metals/premium_{metal}.csv"
    out_path = getattr(args, "out", None) or out_default
    return run(
        metal=metal,
        costs_path=getattr(args, "costs", "out/metals/costs.csv"),
        out_path=out_path,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
