"""Shared test fixtures for metals module tests.

Provides common test data, factory functions, and utilities to reduce
duplication across metals test files.
"""
from __future__ import annotations

import csv
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from metals.costs_common import COSTS_CSV_FIELDS, G_PER_OZ
from metals.cost_extractor import MessageInfo

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
    'make_message_info',
    'make_mock_gmail_client',
    'make_mock_outlook_client',
    'read_csv_as_dicts',
    'assert_csv_content',
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


# Message/Email test data factories
def make_message_info(
    msg_id: str = "msg123",
    subject: str = "Order Confirmation",
    from_header: str = "noreply@td.com",
    body_text: str = "Your order has been received.",
    received_date: str = DEFAULT_DATE,
    received_ms: Optional[int] = None,
) -> MessageInfo:
    """Create a MessageInfo instance with sensible defaults.

    Args:
        msg_id: Message ID
        subject: Email subject line
        from_header: Sender email address
        body_text: Email body content
        received_date: Date received (ISO format)
        received_ms: Optional timestamp in milliseconds

    Returns:
        MessageInfo instance
    """
    return MessageInfo(
        msg_id=msg_id,
        subject=subject,
        from_header=from_header,
        body_text=body_text,
        received_date=received_date,
        received_ms=received_ms,
    )


# Mock client factories
def make_mock_gmail_client(
    message_ids: Optional[List[str]] = None,
    messages: Optional[Dict[str, Dict[str, Any]]] = None,
) -> MagicMock:
    """Create a mock GmailClient with common test setup.

    Args:
        message_ids: List of message IDs to return from list_message_ids
        messages: Dict mapping message_id -> message dict for get_message

    Returns:
        MagicMock configured as a GmailClient

    Example:
        client = make_mock_gmail_client(
            message_ids=['msg1', 'msg2'],
            messages={
                'msg1': {'subject': 'Test', 'body': 'Content'}
            }
        )
    """
    mock_client = MagicMock()
    mock_client.list_message_ids.return_value = message_ids or []

    if messages:
        mock_client.get_message.side_effect = lambda mid, **kwargs: messages.get(mid, {})
    else:
        mock_client.get_message.return_value = {}

    # Common static method
    mock_client.headers_to_dict.return_value = {"subject": "Default Subject"}

    return mock_client


def make_mock_outlook_client(
    message_ids: Optional[List[str]] = None,
    messages: Optional[Dict[str, Dict[str, Any]]] = None,
) -> MagicMock:
    """Create a mock OutlookClient with common test setup.

    Args:
        message_ids: List of message IDs to return from search
        messages: Dict mapping message_id -> message dict

    Returns:
        MagicMock configured as an OutlookClient

    Example:
        client = make_mock_outlook_client(
            message_ids=['msg1'],
            messages={'msg1': {'subject': 'Order', 'body': {'content': 'Text'}}}
        )
    """
    mock_client = MagicMock()

    # Configure search_messages to return message IDs
    if message_ids:
        mock_messages = [{'id': mid} for mid in message_ids]
        mock_client.search_messages.return_value = mock_messages
    else:
        mock_client.search_messages.return_value = []

    # Configure get_message
    if messages:
        mock_client.get_message.side_effect = lambda mid: messages.get(mid, {})
    else:
        mock_client.get_message.return_value = {}

    return mock_client


# CSV testing utilities
def read_csv_as_dicts(path: str) -> List[Dict[str, str]]:
    """Read a CSV file and return rows as list of dicts.

    Args:
        path: Path to CSV file

    Returns:
        List of row dicts with string values
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def assert_csv_content(
    test_case,
    csv_path: str,
    expected_rows: int,
    expected_values: Optional[Dict[int, Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Assert CSV file contents match expectations.

    Args:
        test_case: unittest.TestCase instance (for assertions)
        csv_path: Path to CSV file to check
        expected_rows: Expected number of data rows (excluding header)
        expected_values: Optional dict mapping row_index -> {col: value}

    Returns:
        List of row dicts for further assertions

    Example:
        rows = assert_csv_content(
            self,
            'out.csv',
            expected_rows=2,
            expected_values={
                0: {'vendor': 'TD', 'metal': 'gold'},
                1: {'vendor': 'Costco', 'metal': 'silver'}
            }
        )
    """
    rows = read_csv_as_dicts(csv_path)
    test_case.assertEqual(
        len(rows), expected_rows,
        f"Expected {expected_rows} rows, got {len(rows)}"
    )

    if expected_values:
        for row_idx, expected_cols in expected_values.items():
            for col, expected_val in expected_cols.items():
                actual_val = rows[row_idx].get(col)
                test_case.assertEqual(
                    actual_val, expected_val,
                    f"Row {row_idx}, col '{col}': expected '{expected_val}', got '{actual_val}'"
                )

    return rows
