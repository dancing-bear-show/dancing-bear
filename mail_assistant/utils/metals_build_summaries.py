from __future__ import annotations

"""
Build gold/silver summary CSVs from costs.csv for Excel merge/publish.

Reads out/metals/costs.csv and writes:
  - out/metals/gold_summary.csv
  - out/metals/silver_summary.csv

Each summary has columns: date,order_id,vendor,total_oz,cost_per_oz
"""

import argparse
import csv
from pathlib import Path
from typing import List


def run(costs_path: str, out_dir: str) -> int:
    p = Path(costs_path)
    if not p.exists():
        raise SystemExit(f"costs file not found: {p}")
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    gold: List[List[str]] = [["date", "order_id", "vendor", "total_oz", "cost_per_oz"]]
    silver: List[List[str]] = [["date", "order_id", "vendor", "total_oz", "cost_per_oz"]]
    for r in rows:
        m = (r.get("metal") or "").strip().lower()
        if m not in ("gold", "silver"):
            continue
        date = (r.get("date") or "").strip()
        order_id = (r.get("order_id") or "").strip()
        vendor = (r.get("vendor") or "").strip()
        total_oz = str(r.get("total_oz") or "")
        cpo = str(r.get("cost_per_oz") or "")
        if m == "gold":
            gold.append([date, order_id, vendor, total_oz, cpo])
        else:
            silver.append([date, order_id, vendor, total_oz, cpo])
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    with (outp / "gold_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(gold)
    with (outp / "silver_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(silver)
    print(f"wrote {outp/'gold_summary.csv'} and {outp/'silver_summary.csv'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build gold/silver summary CSVs from costs.csv")
    p.add_argument("--costs", default="out/metals/costs.csv")
    p.add_argument("--out-dir", default="out/metals")
    args = p.parse_args(argv)
    return run(costs_path=getattr(args, "costs", "out/metals/costs.csv"), out_dir=getattr(args, "out_dir", "out/metals"))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

