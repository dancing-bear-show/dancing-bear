"""Dataclasses, parser classes, and shared utilities for vendor email parsing.

Re-export shim: implementation split into vendors_parse_core and vendors_parse_vendor.
"""
from __future__ import annotations

from .vendors_parse_core import (  # noqa: F401
    LineItem,
    PriceHit,
    PriceSearchContext,
    BundleSearchContext,
    DEFAULT_PRICE_BAN,
    _WEIGHT_PATTERNS,
    _WEIGHT_PARSERS,
    _PAT_UNIT,
    _PAT_TOTAL,
    iter_nearby_lines,
    _qty_from_line,
    find_qty_near,
    infer_metal_from_context,
    _parse_frac_match,
    _parse_decimal_match,
    _parse_grams_match,
    _parse_weight_match,
    extract_basic_line_items,
    dedupe_line_items,
    _extract_bundle_qty_from_pattern,
    _extract_bundle_qty_from_sku,
    find_bundle_qty,
    _parse_price_amount,
    _classify_price_kind,
    extract_price_from_lines,
    _enhance_item_qty,
)
from .vendors_parse_vendor import (  # noqa: F401
    VendorParser,
    TDParser,
    CostcoParser,
    RCMParser,
)
