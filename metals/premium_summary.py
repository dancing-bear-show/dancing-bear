"""
Summarize overall premium paid and costs over time (monthly) for metals.

Reads the detailed per-order premium CSVs produced by metals_premium.py and
emits:
  - A combined summary CSV (overall totals per metal and combined)
  - A monthly time-series CSV by metal
Also prints a concise text summary.

Usage:
  python -m mail.utils.metals_premium_summary \
    --silver out/metals/premium_silver.csv \
    --gold out/metals/premium_gold.csv \
    --out-summary out/metals/premium_overview_summary.csv \
    --out-monthly out/metals/premium_overview_monthly.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class PremRow:
    date: str
    vendor: str
    order_id: str
    metal: str
    cost_per_oz: float
    spot_cad: float
    total_oz: float


def _read_premium_csv(path: Optional[str], metal: str) -> List[PremRow]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: List[PremRow] = []
    with p.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                m = (row.get("metal") or metal or "").strip().lower()
                if m != metal:
                    continue
                out.append(
                    PremRow(
                        date=(row.get("date") or "").strip(),
                        vendor=(row.get("vendor") or "").strip(),
                        order_id=(row.get("order_id") or "").strip(),
                        metal=m,
                        cost_per_oz=float(row.get("cost_per_oz_cad") or 0.0),
                        spot_cad=float(row.get("spot_cad") or 0.0),
                        total_oz=float(row.get("total_oz") or 0.0),
                    )
                )
            except Exception:
                continue
    return out


def _summarize(rows: Iterable[PremRow]) -> Dict[str, float]:
    tot_oz = 0.0
    tot_spent = 0.0
    tot_spot = 0.0
    for r in rows:
        if r.total_oz <= 0 or r.cost_per_oz <= 0 or r.spot_cad <= 0:
            continue
        tot_oz += r.total_oz
        tot_spent += r.cost_per_oz * r.total_oz
        tot_spot += r.spot_cad * r.total_oz
    tot_prem = tot_spent - tot_spot
    avg_cost = (tot_spent / tot_oz) if tot_oz > 0 else 0.0
    avg_spot = (tot_spot / tot_oz) if tot_oz > 0 else 0.0
    avg_prem_per_oz = (tot_prem / tot_oz) if tot_oz > 0 else 0.0
    avg_prem_pct = (avg_prem_per_oz / avg_spot) if avg_spot > 0 else 0.0
    return {
        "total_oz": tot_oz,
        "total_spent_cad": tot_spent,
        "spot_value_cad": tot_spot,
        "total_premium_cad": tot_prem,
        "avg_cost_per_oz": avg_cost,
        "avg_spot_per_oz": avg_spot,
        "avg_premium_per_oz": avg_prem_per_oz,
        "avg_premium_pct": avg_prem_pct,
    }


def _monthly(rows: Iterable[PremRow]) -> Dict[str, Dict[str, float]]:
    by_month = defaultdict(lambda: {"orders": 0.0, "total_oz": 0.0, "spent": 0.0, "spot": 0.0})
    for r in rows:
        if not r.date:
            continue
        mo = r.date[:7]
        b = by_month[mo]
        b["orders"] += 1
        b["total_oz"] += r.total_oz
        b["spent"] += r.cost_per_oz * r.total_oz
        b["spot"] += r.spot_cad * r.total_oz
    return by_month


def run(silver_csv: Optional[str], gold_csv: Optional[str], out_summary: str, out_monthly: str) -> int:
    silver = _read_premium_csv(silver_csv, "silver")
    gold = _read_premium_csv(gold_csv, "gold")
    rows_all = silver + gold

    # Overall summaries
    sum_s = _summarize(silver)
    sum_g = _summarize(gold)
    sum_all = _summarize(rows_all)

    # Monthly per-metal
    ms = _monthly(silver)
    mg = _monthly(gold)

    # Write summary CSV
    srows = [[
        "metal", "total_orders", "total_oz", "total_spent_cad", "spot_value_cad",
        "total_premium_cad", "avg_cost_per_oz", "avg_spot_per_oz", "avg_premium_per_oz", "avg_premium_pct",
    ]]
    srows.append([
        "silver", len(silver), f"{sum_s['total_oz']:.3f}", f"{sum_s['total_spent_cad']:.2f}", f"{sum_s['spot_value_cad']:.2f}",
        f"{sum_s['total_premium_cad']:.2f}", f"{sum_s['avg_cost_per_oz']:.2f}", f"{sum_s['avg_spot_per_oz']:.2f}",
        f"{sum_s['avg_premium_per_oz']:.2f}", f"{sum_s['avg_premium_pct']*100:.2f}%",
    ])
    srows.append([
        "gold", len(gold), f"{sum_g['total_oz']:.3f}", f"{sum_g['total_spent_cad']:.2f}", f"{sum_g['spot_value_cad']:.2f}",
        f"{sum_g['total_premium_cad']:.2f}", f"{sum_g['avg_cost_per_oz']:.2f}", f"{sum_g['avg_spot_per_oz']:.2f}",
        f"{sum_g['avg_premium_per_oz']:.2f}", f"{sum_g['avg_premium_pct']*100:.2f}%",
    ])
    srows.append([
        "combined", len(rows_all), f"{sum_all['total_oz']:.3f}", f"{sum_all['total_spent_cad']:.2f}", f"{sum_all['spot_value_cad']:.2f}",
        f"{sum_all['total_premium_cad']:.2f}", f"{sum_all['avg_cost_per_oz']:.2f}", f"{sum_all['avg_spot_per_oz']:.2f}",
        f"{sum_all['avg_premium_per_oz']:.2f}", f"{sum_all['avg_premium_pct']*100:.2f}%",
    ])

    sp = Path(out_summary)
    sp.parent.mkdir(parents=True, exist_ok=True)
    with sp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(srows)

    # Write monthly CSV (rows per (month, metal))
    mrows = [[
        "month", "metal", "orders", "total_oz", "total_spent_cad", "spot_value_cad", "total_premium_cad",
        "avg_cost_per_oz", "avg_spot_per_oz", "avg_premium_per_oz",
    ]]
    for mo, b in sorted(ms.items()):
        spent = b["spent"]; spot = b["spot"]; oz = b["total_oz"]
        prem = spent - spot
        mrows.append([
            mo, "silver", int(b["orders"]), f"{oz:.3f}", f"{spent:.2f}", f"{spot:.2f}", f"{prem:.2f}",
            f"{(spent/oz) if oz else 0:.2f}", f"{(spot/oz) if oz else 0:.2f}", f"{(prem/oz) if oz else 0:.2f}",
        ])
    for mo, b in sorted(mg.items()):
        spent = b["spent"]; spot = b["spot"]; oz = b["total_oz"]
        prem = spent - spot
        mrows.append([
            mo, "gold", int(b["orders"]), f"{oz:.3f}", f"{spent:.2f}", f"{spot:.2f}", f"{prem:.2f}",
            f"{(spent/oz) if oz else 0:.2f}", f"{(spot/oz) if oz else 0:.2f}", f"{(prem/oz) if oz else 0:.2f}",
        ])

    mp = Path(out_monthly)
    mp.parent.mkdir(parents=True, exist_ok=True)
    with mp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(mrows)

    # Print concise overview
    def fmt_money(x: float) -> str:
        return f"C${x:,.2f}"

    print("overall summary:")
    for label, s in ("Silver", sum_s), ("Gold", sum_g), ("Combined", sum_all):
        print(
            f"- {label}: oz={s['total_oz']:.3f}, spent={fmt_money(s['total_spent_cad'])}, "
            f"spot={fmt_money(s['spot_value_cad'])}, premium={fmt_money(s['total_premium_cad'])}, "
            f"avg prem/oz={s['avg_premium_per_oz']:.2f} ({s['avg_premium_pct']*100:.2f}%)"
        )

    print(f"wrote {sp} and {mp}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Summarize premium and costs overall and monthly from premium CSVs")
    p.add_argument("--silver", default="out/metals/premium_silver.csv")
    p.add_argument("--gold", default="out/metals/premium_gold.csv")
    p.add_argument("--out-summary", default="out/metals/premium_overview_summary.csv")
    p.add_argument("--out-monthly", default="out/metals/premium_overview_monthly.csv")
    args = p.parse_args(argv)
    return run(
        silver_csv=getattr(args, "silver", None),
        gold_csv=getattr(args, "gold", None),
        out_summary=getattr(args, "out_summary", "out/metals/premium_overview_summary.csv"),
        out_monthly=getattr(args, "out_monthly", "out/metals/premium_overview_monthly.csv"),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

