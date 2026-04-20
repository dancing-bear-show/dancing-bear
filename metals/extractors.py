"""Precious metals extraction logic.

Core parsing patterns for extracting gold/silver amounts from order emails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .constants import (
    G_PER_OZ,
    PAT_FRAC_OZ as PAT_FRAC,
    PAT_DECIMAL_OZ as PAT_OZ,
    PAT_GRAMS,
    PAT_ORDER_ID,
)


@dataclass
class MetalsAmount:
    """Extracted metals amounts."""
    gold_oz: float = 0.0
    silver_oz: float = 0.0

    def __add__(self, other: "MetalsAmount") -> "MetalsAmount":
        return MetalsAmount(
            gold_oz=self.gold_oz + other.gold_oz,
            silver_oz=self.silver_oz + other.silver_oz,
        )

    def has_metals(self) -> bool:
        return self.gold_oz > 0 or self.silver_oz > 0


@dataclass
class OrderExtraction:
    """Extracted order with metals amounts."""
    order_id: str
    message_id: str
    gold_oz: float
    silver_oz: float
    subject: str = ""
    date_ms: int = 0


def normalize_text(text: str) -> str:
    """Normalize text for parsing (replace unicode dashes, etc.)."""
    return (text or "").replace("\u2013", "-").replace("\u2014", "-")


def extract_order_id(subject: str, text: str) -> str | None:
    """Extract order ID from subject or body text."""
    m = PAT_ORDER_ID.search(subject or "") or PAT_ORDER_ID.search(text or "")
    return m.group(1) if m else None


def _accumulate_oz(
    gold_oz: float,
    silver_oz: float,
    metal: str,
    oz_unit: float,
    qty: float,
    key: Tuple[str, float, float],
    seen: set,
) -> Tuple[float, float]:
    """Accumulate oz totals if key not already seen."""
    if key in seen:
        return gold_oz, silver_oz
    seen.add(key)
    if metal.startswith("gold"):
        gold_oz += oz_unit * qty
    elif metal.startswith("silver"):
        silver_oz += oz_unit * qty
    return gold_oz, silver_oz


def _parse_frac_matches(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in PAT_FRAC.finditer(ln):
        num = float(m.group(1))
        den = float(m.group(2) or 1)
        metal = (m.group(3) or "").lower()
        qty = float(m.group(4) or 1)
        oz_unit = num / max(den, 1.0)
        gold_oz, silver_oz = _accumulate_oz(gold_oz, silver_oz, metal, oz_unit, qty, (metal, round(oz_unit, 6), qty), seen)
    return gold_oz, silver_oz


def _parse_oz_matches(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in PAT_OZ.finditer(ln):
        wt = float(m.group(1))
        metal = (m.group(2) or "").lower()
        qty = float(m.group(3) or 1)
        gold_oz, silver_oz = _accumulate_oz(gold_oz, silver_oz, metal, wt, qty, (metal, round(wt, 6), qty), seen)
    return gold_oz, silver_oz


def _parse_gram_matches(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in PAT_GRAMS.finditer(ln):
        wt_g = float(m.group(1))
        metal = (m.group(3) or "").lower()
        qty = float(m.group(4) or 1)
        oz_unit = wt_g / G_PER_OZ
        gold_oz, silver_oz = _accumulate_oz(gold_oz, silver_oz, metal, oz_unit, qty, (metal, round(oz_unit, 6), qty), seen)
    return gold_oz, silver_oz


def extract_amounts(text: str) -> MetalsAmount:
    """Extract gold and silver ounces from text.

    Supports:
    - Fractional ounces (e.g., "1/10 oz Gold")
    - Decimal ounces (e.g., "1 oz Silver")
    - Grams (e.g., "31.1 g Gold")
    - Quantities (e.g., "1 oz Gold x 5")
    """
    gold_oz = 0.0
    silver_oz = 0.0
    t = normalize_text(text)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    seen: set[Tuple[str, float, float]] = set()

    for ln in lines:
        gold_oz, silver_oz = _parse_frac_matches(ln, gold_oz, silver_oz, seen)
        gold_oz, silver_oz = _parse_oz_matches(ln, gold_oz, silver_oz, seen)
        gold_oz, silver_oz = _parse_gram_matches(ln, gold_oz, silver_oz, seen)

    return MetalsAmount(gold_oz=gold_oz, silver_oz=silver_oz)
