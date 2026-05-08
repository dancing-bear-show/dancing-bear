"""Precious metals extraction logic.

Core parsing patterns for extracting gold/silver amounts from order emails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

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


@dataclass
class OzAccumulator:
    """Mutable accumulator for gold/silver ounce totals with dedup tracking."""
    gold_oz: float = 0.0
    silver_oz: float = 0.0
    seen: Optional[set] = None

    def __post_init__(self) -> None:
        if self.seen is None:
            self.seen = set()

    def add(self, metal: str, oz_unit: float, qty: float, key: Tuple[str, float, float]) -> None:
        """Accumulate oz totals if key not already seen."""
        if key in self.seen:
            return
        self.seen.add(key)
        if metal.startswith("gold"):
            self.gold_oz += oz_unit * qty
        elif metal.startswith("silver"):
            self.silver_oz += oz_unit * qty


def _parse_frac_matches(ln: str, acc: OzAccumulator) -> None:
    for m in PAT_FRAC.finditer(ln):
        num = float(m.group(1))
        den = float(m.group(2) or 1)
        metal = (m.group(3) or "").lower()
        qty = float(m.group(4) or 1)
        oz_unit = num / max(den, 1.0)
        acc.add(metal, oz_unit, qty, (metal, round(oz_unit, 6), qty))


def _parse_oz_matches(ln: str, acc: OzAccumulator) -> None:
    for m in PAT_OZ.finditer(ln):
        wt = float(m.group(1))
        metal = (m.group(2) or "").lower()
        qty = float(m.group(3) or 1)
        acc.add(metal, wt, qty, (metal, round(wt, 6), qty))


def _parse_gram_matches(ln: str, acc: OzAccumulator) -> None:
    for m in PAT_GRAMS.finditer(ln):
        wt_g = float(m.group(1))
        metal = (m.group(3) or "").lower()
        qty = float(m.group(4) or 1)
        oz_unit = wt_g / G_PER_OZ
        acc.add(metal, oz_unit, qty, (metal, round(oz_unit, 6), qty))


def extract_amounts(text: str) -> MetalsAmount:
    """Extract gold and silver ounces from text.

    Supports:
    - Fractional ounces (e.g., "1/10 oz Gold")
    - Decimal ounces (e.g., "1 oz Silver")
    - Grams (e.g., "31.1 g Gold")
    - Quantities (e.g., "1 oz Gold x 5")
    """
    t = normalize_text(text)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    acc = OzAccumulator()

    for ln in lines:
        _parse_frac_matches(ln, acc)
        _parse_oz_matches(ln, acc)
        _parse_gram_matches(ln, acc)

    return MetalsAmount(gold_oz=acc.gold_oz, silver_oz=acc.silver_oz)
