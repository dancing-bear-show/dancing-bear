"""Cost computation and output building for Outlook RCM precious metals cost parsing."""
from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Tuple

from .outlook_costs_extract import (
    ConfirmationRowContext,
    GoldRowContext,
    OutlookCostExtractor,
)
from .pipeline import default_costs_path

# Test helper defaults
_TEST_EXTRACTOR_DEFAULTS = ('outlook_personal', default_costs_path())


def _summarize_ounces(items: List[Dict], metal_guess: str) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
    """Summarize ounces and units per metal."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._summarize_ounces(items, metal_guess)


def _compute_confirmation_line_costs(
    body: str, gold_items: List[Dict], ctx: ConfirmationRowContext
) -> Tuple[float, List[Dict[str, str | float]]]:
    """Compute line costs from confirmation email 'Total $X CAD' sequences."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._compute_confirmation_line_costs(body, gold_items, ctx)


def _compute_proximity_line_costs(gold_items: List[Dict], lines: List[str]) -> float:
    """Compute line costs using proximity-based price extraction."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._compute_proximity_line_costs(gold_items, lines)


def _build_gold_row(ctx: GoldRowContext) -> Dict[str, str | float]:
    """Build a single aggregated gold row."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._build_gold_row(ctx)


def run(profile: str, out_path: str, days: int = 365) -> int:
    """Run Outlook cost extraction."""
    extractor = OutlookCostExtractor(profile, out_path, days)
    return extractor.run()


def main(argv: Optional[List[str]] = None) -> int:
    default_out = default_costs_path()
    p = argparse.ArgumentParser(description='Extract RCM costs from Outlook and merge into costs.csv')
    p.add_argument('--profile', default='outlook_personal')
    p.add_argument('--out', default=default_out)
    p.add_argument('--days', type=int, default=365)
    args = p.parse_args(argv)
    return run(
        profile=getattr(args, 'profile', 'outlook_personal'),
        out_path=getattr(args, 'out', default_out),
        days=int(getattr(args, 'days', 365))
    )


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
