"""Vendor-specific parsers for precious metals email extraction."""
from __future__ import annotations

from .vendors_parse import (  # noqa: F401
    LineItem,
    PriceHit,
    PriceSearchContext,
    BundleSearchContext,
    VendorParser,
    TDParser,
    CostcoParser,
    RCMParser,
    iter_nearby_lines,
    find_qty_near,
    infer_metal_from_context,
    extract_basic_line_items,
    dedupe_line_items,
    find_bundle_qty,
    extract_price_from_lines,
    DEFAULT_PRICE_BAN,
    _WEIGHT_PATTERNS,
    _parse_weight_match,
)
from .vendors_search import (  # noqa: F401
    ALL_VENDORS,
    GMAIL_VENDORS,
    OUTLOOK_VENDORS,
    get_vendor_for_sender,
)

__all__ = [
    'LineItem',
    'PriceHit',
    'PriceSearchContext',
    'BundleSearchContext',
    'VendorParser',
    'TDParser',
    'CostcoParser',
    'RCMParser',
    'ALL_VENDORS',
    'GMAIL_VENDORS',
    'OUTLOOK_VENDORS',
    'get_vendor_for_sender',
    'extract_basic_line_items',
    'dedupe_line_items',
    'find_qty_near',
    'find_bundle_qty',
    'infer_metal_from_context',
    'iter_nearby_lines',
    'extract_price_from_lines',
]
