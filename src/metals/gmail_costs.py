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
  python -m metals.costs --profile gmail_personal --out out/metals/costs.csv
"""
from __future__ import annotations

import argparse
from typing import List

# These names must live at module level for @patch('metals.gmail_costs.<name>') to work
from mail.config_resolver import resolve_paths_profile  # noqa: F401
from mail.gmail_api import GmailClient  # noqa: F401

from .constants import (  # noqa: F401
    PAT_FRAC_OZ as _PAT_FRAC,
    PAT_DECIMAL_OZ as _PAT_OZ,
    PAT_GRAMS as _PAT_G,
    QTY_PATTERNS as _PAT_QTY_LIST,
)
from .gmail_costs_qty import (  # noqa: F401
    LineItemContext,
    ExtractionContext,
    PriceLineContext,
    CandidateLineContext,
    _PAT_UNIT_PRICE,
    _extract_first_match_group,
    _explicit_qty_near,
    _bundle_qty_near,
    _get_metal_maps,
    _check_sku_match,
    _check_phrase_match,
    _unit_oz_override_near,
    _extract_leading_qty,
    _determine_quantity,
    _apply_qty_heuristics,
    _parse_frac_match,
    _parse_oz_match,
    _parse_gram_match,
    _extract_line_items,
    _build_uoz_patterns,
    _try_anchored_extraction,
    _determine_price_kind,
    _check_uoz_in_neighbors,
    _is_valid_price_line,
    _process_candidate_line,
    _extract_amount_near_line,
)
from .gmail_costs_extract import (  # noqa: F401
    OrderRowData,
    _ORDER_PAT,
    _COSTCO_ORDER_PAT,
    _CANCELLED_PAT,
    _QUERIES,
    _classify_vendor,
    _is_order_confirmation,
    _is_cancelled,
    _fetch_message_ids,
    _compute_line_costs,
    _allocate_costs,
    _build_order_rows,
    _extract_items_from_message,
    _process_messages,
    _aggregate_metals,
    _process_order,
    GmailCostExtractor,
)


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Extract costs and cost-per-oz from Gmail order emails')
    p.add_argument('--profile', default='gmail_personal')
    p.add_argument('--out', default='out/metals/costs.csv')
    args = p.parse_args(argv)

    extractor = GmailCostExtractor(
        profile=getattr(args, 'profile', 'gmail_personal'),
        out_path=getattr(args, 'out', 'out/metals/costs.csv'),
        days=365,
    )
    return extractor.run()


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
