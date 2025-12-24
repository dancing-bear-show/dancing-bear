"""Precious metals extraction logic.

Core parsing patterns for extracting gold/silver amounts from order emails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

# Grams per troy ounce
G_PER_OZ = 31.1035

# Regex patterns for extracting metal amounts
PAT_FRAC = re.compile(
    r"(?i)\b(\d+)\s*/\s*(\d+)\s*oz\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)
PAT_OZ = re.compile(
    r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*oz\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)
PAT_GRAMS = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)
PAT_ORDER_ID = re.compile(r"(?i)order\s*#?\s*(\d{6,})")


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

    # Track unique line items to avoid double counting
    seen_items: set[Tuple[str, float, float]] = set()

    for ln in lines:
        # Fractional ounces (e.g., "1/10 oz Gold")
        for m in PAT_FRAC.finditer(ln):
            num = float(m.group(1))
            den = float(m.group(2) or 1)
            metal = (m.group(3) or "").lower()
            qty = float(m.group(4) or 1)
            oz_unit = num / max(den, 1.0)
            key = (metal, round(oz_unit, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith("gold"):
                gold_oz += oz_unit * qty
            elif metal.startswith("silver"):
                silver_oz += oz_unit * qty

        # Decimal ounces (e.g., "1 oz Silver")
        for m in PAT_OZ.finditer(ln):
            wt = float(m.group(1))
            metal = (m.group(2) or "").lower()
            qty = float(m.group(3) or 1)
            key = (metal, round(wt, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith("gold"):
                gold_oz += wt * qty
            elif metal.startswith("silver"):
                silver_oz += wt * qty

        # Grams (e.g., "31.1 g Gold")
        for m in PAT_GRAMS.finditer(ln):
            wt_g = float(m.group(1))
            metal = (m.group(3) or "").lower()
            qty = float(m.group(4) or 1)
            oz_unit = wt_g / G_PER_OZ
            key = (metal, round(oz_unit, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith("gold"):
                gold_oz += oz_unit * qty
            elif metal.startswith("silver"):
                silver_oz += oz_unit * qty

    return MetalsAmount(gold_oz=gold_oz, silver_oz=silver_oz)
