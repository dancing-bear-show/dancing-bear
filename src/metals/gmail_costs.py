"""
Extract per-order cost per ounce from Gmail order emails (TD Precious Metals and Costco).

Outputs a CSV with: vendor,date,metal,currency,cost_total,cost_per_oz,order_id,subject

Heuristics:
- Deduplicates by order id, keeping the latest email per order.
- For TD emails, tries to parse 'Total' or 'Subtotal' currency amounts.
- Computes cost_per_oz = cost_total / total_oz (sum of all line items in the order for that metal).
- If an order mixes metals, computes a row per metal using the same order total (note: this can
  over-approximate if costs differ by metal; most orders contain a single metal).

Usage:
  python -m metals.costs --profile gmail_personal --out costs.csv
"""
from __future__ import annotations

import argparse
from typing import List

from .gmail_costs_extract import GmailCostExtractor
from .pipeline import default_costs_path


def main(argv: List[str] | None = None) -> int:
    default_out = default_costs_path()
    p = argparse.ArgumentParser(description='Extract costs and cost-per-oz from Gmail order emails')
    p.add_argument('--profile', default='gmail_personal')
    p.add_argument('--out', default=default_out)
    args = p.parse_args(argv)

    extractor = GmailCostExtractor(
        profile=getattr(args, 'profile', 'gmail_personal'),
        out_path=getattr(args, 'out', default_out),
        days=365,
    )
    return extractor.run()


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
