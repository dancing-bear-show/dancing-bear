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
    'make_cost_row',
    'make_gold_row',
    'make_silver_row',
    'write_costs_csv',
    'temp_costs_csv',
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
