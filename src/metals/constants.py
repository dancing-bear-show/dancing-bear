"""Shared constants for precious metals extraction.

Centralizes conversion factors, regex patterns, SKU mappings, and CSV field names
used across the metals module to eliminate duplication.
"""
from __future__ import annotations

import re
from typing import Dict, List

# =============================================================================
# Conversion Constants
# =============================================================================

G_PER_OZ = 31.1035  # Grams per troy ounce


# =============================================================================
# Weight Extraction Patterns
# =============================================================================

# Fractional ounces (e.g., "1/10 oz gold x 5")
PAT_FRAC_OZ = re.compile(
    r"(?i)\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)

# Decimal ounces (e.g., "1.5 oz silver x 3")
# Negative lookbehind prevents matching "10" from "1/10 oz"
PAT_DECIMAL_OZ = re.compile(
    r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*[- ]?oz\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)

# Grams (e.g., "31.1 grams gold")
PAT_GRAMS = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)


# =============================================================================
# Quantity Detection Patterns
# =============================================================================

# Explicit quantity patterns (e.g., "Qty: 5", "x 3")
QTY_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?i)\bqty\s*[:#]?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bquantity\s*[:#]?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bx\s*(\d{1,3})\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*x\b"),
]

# Bundle quantity patterns (e.g., "25-pack", "roll of 25")
BUNDLE_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?i)\b(\d{1,3})\s*[- ]?pack\b"),
    re.compile(r"(?i)\bpack\s*of\s*(\d{1,3})\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*coins?\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*ct\b"),
    re.compile(r"(?i)\b(?:roll|tube)\s*of\s*(\d{1,3})\b"),
]


# =============================================================================
# Metadata Extraction Patterns
# =============================================================================

# Order ID pattern (e.g., "Order #123456")
PAT_ORDER_ID = re.compile(r"(?i)order\s*#?\s*(\d{6,})")

# SKU/Item number pattern (e.g., "Item #: 3796875")
PAT_SKU = re.compile(r"(?i)\bitem(?:\s*(?:#|number)\s*)?:?\s*(\d{5,})\b")

# Cancelled order detection
PAT_CANCELLED = re.compile(r"(?i)\bcancel(?:led|ed)\b")

# Leading quantity pattern (e.g., "2 x 1 oz Gold")
PAT_LEADING_QTY = re.compile(r"(?i)\b(\d{1,3})\s*x\b")


# =============================================================================
# Price Extraction Patterns
# =============================================================================

# Money pattern: matches C$1,234.56 or CAD$1,234.56 or CAD $1,234.56 or $1,234.56
MONEY_PATTERN = re.compile(
    r"(?i)(C\$|CAD\s*\$|CAD\$|\$)\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)"
)

# Default banned terms for price line filtering
PRICE_BAN_DEFAULT = re.compile(
    r"(?i)\b(subtotal|shipping|tax|order number|order #)\b"
)

# RCM-specific banned terms (includes Canadian taxes)
PRICE_BAN_RCM = re.compile(
    r"(?i)(subtotal|shipping|handling|tax|gst|hst|pst|savings|"
    r"free\s+shipping|orders?\s+over|threshold)"
)


# =============================================================================
# SKU Mappings
# =============================================================================

# SKU to bundle quantity (tubes, rolls, packs)
SKU_BUNDLE_MAP: Dict[str, float] = {
    '3796875': 25.0,  # 25 x 1 oz tube (Costco)
}

# SKU to unit size overrides - Silver
SKU_UNIT_MAP_SILVER: Dict[str, float] = {
    '2796876': 10.0,  # 10 oz silver bar
}

# SKU to unit size overrides - Gold
SKU_UNIT_MAP_GOLD: Dict[str, float] = {
    '5882020': 0.25,  # 1/4 oz Canadian Gold Maple Leaf (Costco)
}

# Product phrase to unit size mapping - Silver
PHRASE_MAP_SILVER: Dict[str, float] = {
    'magnificent maple leaves silver coin': 10.0,
}


# =============================================================================
# CSV Output
# =============================================================================

# CSV field names for costs output
COSTS_CSV_FIELDS: List[str] = [
    'vendor', 'date', 'metal', 'currency', 'cost_total', 'cost_per_oz',
    'order_id', 'subject', 'total_oz', 'unit_count', 'units_breakdown', 'alloc',
]


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Conversion
    'G_PER_OZ',
    # Weight patterns
    'PAT_FRAC_OZ',
    'PAT_DECIMAL_OZ',
    'PAT_GRAMS',
    # Quantity patterns
    'QTY_PATTERNS',
    'BUNDLE_PATTERNS',
    # Metadata patterns
    'PAT_ORDER_ID',
    'PAT_SKU',
    'PAT_CANCELLED',
    'PAT_LEADING_QTY',
    # Price patterns
    'MONEY_PATTERN',
    'PRICE_BAN_DEFAULT',
    'PRICE_BAN_RCM',
    # SKU mappings
    'SKU_BUNDLE_MAP',
    'SKU_UNIT_MAP_SILVER',
    'SKU_UNIT_MAP_GOLD',
    'PHRASE_MAP_SILVER',
    # CSV
    'COSTS_CSV_FIELDS',
]
