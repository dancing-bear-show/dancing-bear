"""Shared test fixtures for metals module tests.

Provides common test data, factory functions, and utilities to reduce
duplication across metals test files.
"""
from __future__ import annotations

import csv
import os
import tempfile
from contextlib import contextmanager
from typing import Dict, List, Optional

from metals.costs_common import COSTS_CSV_FIELDS, G_PER_OZ

# Re-export commonly used constants
__all__ = [
    'G_PER_OZ',
    'COSTS_CSV_FIELDS',
    'COSTS_HEADERS',
    'SAMPLE_VENDORS',
    'SAMPLE_METALS',
    'VENDOR_EMAILS',
    'LINES_5',
    'LINES_3',
    'make_cost_row',
    'make_gold_row',
    'make_silver_row',
    'write_costs_csv',
    'temp_costs_csv',
    'make_price_lines',
]

# CSV headers for costs files
COSTS_HEADERS = [
    "date", "vendor", "metal", "currency", "cost_total", "cost_per_oz",
    "order_id", "subject", "total_oz", "unit_count", "units_breakdown", "alloc"
]

# Sample vendor names
SAMPLE_VENDORS = ["TD", "Costco", "RCM"]

# Sample metals
SAMPLE_METALS = ["gold", "silver"]

# Vendor email addresses for sender matching tests
VENDOR_EMAILS = {
    "TD": ["noreply@td.com", "orders@preciousmetals.td.com", "NoReply@TD.COM"],
    "Costco": ["orders@costco.com", "noreply@orders.costco.com"],
    "RCM": ["noreply@mint.ca", "orders@email.mint.ca", "noreply@royalcanadianmint.ca"],
    "unknown": ["someone@example.com", "other@unknown.org"],
}

# Reusable line arrays for iter_nearby_lines tests
LINES_5 = ["line0", "line1", "line2", "line3", "line4"]
LINES_3 = ["line0", "line1", "line2"]

# Default test values
DEFAULT_DATE = "2024-01-15"
DEFAULT_CURRENCY = "CAD"


def make_cost_row(
    date: str = DEFAULT_DATE,
    vendor: str = "TD",
    metal: str = "gold",
    currency: str = DEFAULT_CURRENCY,
    cost_total: float = 2500.0,
    cost_per_oz: float = 2500.0,
    order_id: str = "12345",
    subject: str = "Order Confirmation",
    total_oz: float = 1.0,
    unit_count: int = 1,
    units_breakdown: str = "1ozx1",
    alloc: str = "line-item",
) -> Dict[str, str | float | int]:
    """Create a cost row dict with sensible defaults."""
    return {
        "date": date,
        "vendor": vendor,
        "metal": metal,
        "currency": currency,
        "cost_total": cost_total,
        "cost_per_oz": cost_per_oz,
        "order_id": order_id,
        "subject": subject,
        "total_oz": total_oz,
        "unit_count": unit_count,
        "units_breakdown": units_breakdown,
        "alloc": alloc,
    }


def make_gold_row(
    vendor: str = "TD",
    date: str = DEFAULT_DATE,
    oz: float = 1.0,
    cost_per_oz: float = 2500.0,
    order_id: str = "12345",
) -> Dict[str, str | float | int]:
    """Create a gold cost row with typical values."""
    return make_cost_row(
        date=date,
        vendor=vendor,
        metal="gold",
        cost_total=oz * cost_per_oz,
        cost_per_oz=cost_per_oz,
        order_id=order_id,
        total_oz=oz,
        units_breakdown=f"{oz}ozx1",
    )


def make_silver_row(
    vendor: str = "TD",
    date: str = DEFAULT_DATE,
    oz: float = 10.0,
    cost_per_oz: float = 35.0,
    order_id: str = "12346",
) -> Dict[str, str | float | int]:
    """Create a silver cost row with typical values."""
    return make_cost_row(
        date=date,
        vendor=vendor,
        metal="silver",
        cost_total=oz * cost_per_oz,
        cost_per_oz=cost_per_oz,
        order_id=order_id,
        total_oz=oz,
        units_breakdown=f"1ozx{int(oz)}",
    )


def write_costs_csv(
    path: str,
    rows: List[Dict[str, str | float | int]],
    headers: Optional[List[str]] = None,
) -> str:
    """Write a costs CSV file with given rows.

    Args:
        path: File path to write
        rows: List of row dicts (use make_cost_row to create)
        headers: Optional custom headers (defaults to COSTS_HEADERS)

    Returns:
        The path to the written file
    """
    hdrs = headers or COSTS_HEADERS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hdrs)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return path


@contextmanager
def temp_costs_csv(rows: List[Dict[str, str | float | int]]):
    """Context manager that yields path to a temporary costs CSV.

    Example:
        with temp_costs_csv([make_gold_row(), make_silver_row()]) as path:
            result = parse_costs(path)
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=COSTS_HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
        f.flush()
        yield f.name
    os.unlink(f.name)


# Premium CSV helpers
PREMIUM_HEADERS = [
    "date", "vendor", "metal", "currency", "cost_per_oz", "total_oz",
    "order_id", "units_breakdown"
]


def make_premium_row(
    date: str = DEFAULT_DATE,
    vendor: str = "TD",
    metal: str = "silver",
    currency: str = DEFAULT_CURRENCY,
    cost_per_oz: float = 35.0,
    total_oz: float = 10.0,
    order_id: str = "12345",
    units_breakdown: str = "1ozx10",
) -> Dict[str, str | float]:
    """Create a premium row dict for CostRow parsing."""
    return {
        "date": date,
        "vendor": vendor,
        "metal": metal,
        "currency": currency,
        "cost_per_oz": cost_per_oz,
        "total_oz": total_oz,
        "order_id": order_id,
        "units_breakdown": units_breakdown,
    }


@contextmanager
def temp_premium_csv(rows: List[Dict[str, str | float]]):
    """Context manager that yields path to a temporary premium CSV."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=PREMIUM_HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
        f.flush()
        yield f.name
    os.unlink(f.name)


# Summary CSV helpers (for build_summaries tests)
SUMMARY_HEADERS = ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]


def make_summary_row(
    date: str = DEFAULT_DATE,
    order_id: str = "12345",
    vendor: str = "TD",
    metal: str = "gold",
    total_oz: float = 1.0,
    cost_per_oz: float = 2500.0,
) -> Dict[str, str | float]:
    """Create a summary row dict for build_summaries tests."""
    return {
        "date": date,
        "order_id": order_id,
        "vendor": vendor,
        "metal": metal,
        "total_oz": total_oz,
        "cost_per_oz": cost_per_oz,
    }


@contextmanager
def temp_summary_csv(rows: List[Dict[str, str | float]]):
    """Context manager that yields path to a temporary summary CSV."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
        f.flush()
        yield f.name
    os.unlink(f.name)


def write_summary_csv(path: str, rows: List[Dict[str, str | float]]) -> str:
    """Write a summary CSV file at the given path."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_HEADERS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return path


# Line item test helpers
def make_line_item_text(
    oz: float = 1.0,
    metal: str = "gold",
    qty: int = 1,
    product: str = "Maple Leaf",
) -> str:
    """Create sample line item text for parsing tests."""
    if qty > 1:
        return f"{oz} oz {metal.title()} {product} x {qty}"
    return f"{oz} oz {metal.title()} {product}"


def make_fractional_oz_text(
    num: int = 1,
    den: int = 10,
    metal: str = "gold",
    qty: int = 1,
) -> str:
    """Create fractional ounce text like '1/10 oz Gold'."""
    base = f"{num}/{den} oz {metal.title()}"
    if qty > 1:
        return f"{base} x {qty}"
    return base


def make_price_lines(
    item_desc: str = "1 oz Gold Coin",
    price: float = 2500.0,
    price_kind: str = "unit",
    include_banned: bool = False,
) -> List[str]:
    """Create test lines for price extraction tests.

    Args:
        item_desc: Item description line
        price: Price amount
        price_kind: 'unit' (adds 'each'), 'total', or 'unknown' (no keyword)
        include_banned: If True, adds a shipping line before price

    Returns:
        List of lines for testing extract_price_from_lines
    """
    lines = [item_desc]
    if include_banned:
        lines.append("Shipping: $25.00")

    price_str = f"${price:,.2f}"
    if price_kind == "unit":
        lines.append(f"Price: {price_str} each")
    elif price_kind == "total":
        lines.append(f"Total: {price_str}")
    else:
        lines.append(price_str)
    return lines
