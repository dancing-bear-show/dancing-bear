"""Vendor-specific parsers for precious metals email extraction."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode

from .constants import (
    G_PER_OZ,
    MONEY_PATTERN,
    PAT_FRAC_OZ,
    PAT_DECIMAL_OZ,
    PAT_GRAMS,
    QTY_PATTERNS,
    BUNDLE_PATTERNS,
    PAT_SKU,
    PRICE_BAN_DEFAULT,
    PRICE_BAN_RCM,
    SKU_BUNDLE_MAP,
    SKU_UNIT_MAP_SILVER,
    SKU_UNIT_MAP_GOLD,
)
from .costs_common import get_price_band


@dataclass
class LineItem:
    """A parsed line item from an order email."""
    metal: str
    unit_oz: float
    qty: float
    idx: int  # line index in source text


@dataclass
class PriceHit:
    """A price found near a line item."""
    amount: float
    kind: str  # 'unit', 'total', or 'unknown'


class VendorParser(ABC):
    """Base class for vendor-specific email parsing."""

    name: str = "Unknown"

    @abstractmethod
    def matches_sender(self, from_header: str) -> bool:
        """Return True if this parser handles emails from this sender."""
        raise NotImplementedError

    @abstractmethod
    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        """Extract line items from email text. Returns (items, lines)."""
        raise NotImplementedError

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Find a price near a line item. Override for vendor-specific logic."""
        return None

    def classify_email(self, subject: str) -> Tuple[str, int]:
        """Classify email type and priority. Returns (type, priority)."""
        return ('other', 0)


# =============================================================================
# Shared Parsing Utilities
# =============================================================================


def iter_nearby_lines(
    lines: List[str], idx: int, window: int, forward_only: bool = False
) -> List[Tuple[int, str]]:
    """Return (line_index, line_text) pairs near idx within window."""
    result: List[Tuple[int, str]] = []
    seen: set[int] = set()
    for d in range(window):
        candidates = [idx + d] if forward_only else [idx + d, idx - d]
        for j in candidates:
            if j in seen or not (0 <= j < len(lines)):
                continue
            seen.add(j)
            result.append((j, lines[j] or ""))
    return result


def find_qty_near(lines: List[str], idx: int, window: int = 4) -> Optional[float]:
    """Find explicit quantity near a line index."""
    for _, ln in iter_nearby_lines(lines, idx, window):
        for pat in QTY_PATTERNS:
            m = pat.search(ln)
            if m:
                raw = m.group(1)
                if raw and raw.isdigit():
                    n = int(raw)
                    if 1 <= n <= 200:
                        return float(n)
    return None


def infer_metal_from_context(text: str) -> str:
    """Infer metal type from surrounding text."""
    t = (text or '').lower()
    if 'gold' in t:
        return 'gold'
    if 'silver' in t:
        return 'silver'
    return ''


def _parse_weight_match(m: re.Match, pattern_type: str) -> Optional[Tuple[float, str, float]]:
    """Parse a weight regex match into (unit_oz, metal, qty). Returns None on error."""
    try:
        if pattern_type == 'frac':
            num, den = float(m.group(1)), float(m.group(2) or 1)
            unit_oz = num / max(den, 1.0)
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
        elif pattern_type == 'decimal':
            unit_oz = float(m.group(1))
            metal = (m.group(2) or '').lower()
            qty = float(m.group(3) or 1)
        elif pattern_type == 'grams':
            unit_oz = float(m.group(1)) / G_PER_OZ
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
        else:
            return None
        return (unit_oz, metal, qty)
    except (ValueError, IndexError):
        return None


# Pattern configs: (pattern, type_key)
_WEIGHT_PATTERNS = [
    (PAT_FRAC_OZ, 'frac'),
    (PAT_DECIMAL_OZ, 'decimal'),
    (PAT_GRAMS, 'grams'),
]


def extract_basic_line_items(text: str) -> Tuple[List[LineItem], List[str]]:
    """Basic line item extraction shared across vendors."""
    items: List[LineItem] = []
    t = normalize_unicode(text or '')
    lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]

    for idx, ln in enumerate(lines):
        for pat, ptype in _WEIGHT_PATTERNS:
            for m in pat.finditer(ln):
                parsed = _parse_weight_match(m, ptype)
                if parsed:
                    unit_oz, metal, qty = parsed
                    items.append(LineItem(metal=metal, unit_oz=unit_oz, qty=qty, idx=idx))

    return items, lines


def dedupe_line_items(items: List[LineItem]) -> List[LineItem]:
    """Deduplicate items by (unit_oz, idx), keeping larger quantities."""
    if not items:
        return items

    buckets: Dict[Tuple[int, int], LineItem] = {}
    for it in items:
        ukey = int(round(it.unit_oz * 1000))
        k = (ukey, it.idx)
        cur = buckets.get(k)
        if not cur:
            buckets[k] = it
        else:
            if it.qty > cur.qty:
                cur.qty = it.qty
            if it.metal and not cur.metal:
                cur.metal = it.metal
    return list(buckets.values())


# Alias for backwards compatibility
DEFAULT_PRICE_BAN = PRICE_BAN_DEFAULT


def find_bundle_qty(
    lines: List[str],
    idx: int,
    sku_map: Optional[Dict[str, float]] = None,
    window: int = 4,
) -> Optional[float]:
    """Find bundle quantity from patterns or SKU mapping."""
    for _, ln in iter_nearby_lines(lines, idx, window):
        # Check bundle patterns
        for pat in BUNDLE_PATTERNS:
            m = pat.search(ln)
            if m:
                for g in range(1, len(m.groups()) + 1):
                    val = m.group(g)
                    if val and val.isdigit():
                        n = int(val)
                        if 2 <= n <= 200:
                            return float(n)
        # Check SKU mapping
        if sku_map:
            m_sku = PAT_SKU.search(ln)
            if m_sku and m_sku.group(1) in sku_map:
                return sku_map[m_sku.group(1)]
    return None


def extract_price_from_lines(
    lines: List[str],
    idx: int,
    metal: str,
    unit_oz: float,
    window: int = 13,
    ban_pattern: Optional[re.Pattern] = None,
    forward_only: bool = False,
) -> Optional[PriceHit]:
    """Shared price extraction logic used by multiple vendors."""
    ban = ban_pattern or DEFAULT_PRICE_BAN
    lb, ub = get_price_band(metal, unit_oz)

    for _, ln in iter_nearby_lines(lines, idx, window, forward_only):
        if ban.search(ln):
            continue

        m = MONEY_PATTERN.search(ln)
        if not m:
            continue

        try:
            amt = float(m.group(2).replace(",", ""))
        except (ValueError, IndexError):
            continue

        if not (lb <= amt <= ub):
            continue

        low = ln.lower()
        if re.search(r"(?i)\b(unit|each|ea|per)\b", low):
            return PriceHit(amount=amt, kind='unit')
        if re.search(r"(?i)\btotal\b", low):
            return PriceHit(amount=amt, kind='total')
        return PriceHit(amount=amt, kind='unknown')

    return None


# =============================================================================
# TD Precious Metals Parser
# =============================================================================

class TDParser(VendorParser):
    """Parser for TD Precious Metals emails."""

    name = "TD"

    # SKU -> bundle size mappings
    SKU_BUNDLE_MAP: Dict[str, float] = {
        '3796875': 25.0,  # 25 x 1 oz tube
    }

    # SKU -> unit oz overrides
    SKU_UNIT_MAP_SILVER: Dict[str, float] = {
        '2796876': 10.0,  # single 10 oz silver bar
    }
    SKU_UNIT_MAP_GOLD: Dict[str, float] = {
        '5882020': 0.25,  # 1/4 oz Canadian Gold Maple Leaf
    }

    def matches_sender(self, from_header: str) -> bool:
        email = self._extract_email(from_header).lower()
        return any(x in email for x in ('td.com', 'tdsecurities.com', 'preciousmetals.td.com'))

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        items, lines = extract_basic_line_items(text)

        for item in items:
            if item.qty == 1.0:
                eq = find_qty_near(lines, item.idx)
                if eq:
                    item.qty = eq
                elif 0.98 <= item.unit_oz <= 1.02:
                    bq = find_bundle_qty(lines, item.idx, self.SKU_BUNDLE_MAP)
                    if bq:
                        item.qty = bq

            uov = self._get_unit_oz_override(lines, item.idx, item.metal)
            if uov:
                item.unit_oz = uov

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        return extract_price_from_lines(lines, idx, metal, unit_oz)

    def _extract_email(self, from_header: str) -> str:
        m = re.search(r"<([^>]+)>", from_header or '')
        return m.group(1) if m else (from_header or '')

    def _get_unit_oz_override(self, lines: List[str], idx: int, metal: str) -> Optional[float]:
        """Get unit oz override from SKU mapping."""
        sku_map = self.SKU_UNIT_MAP_SILVER if metal == 'silver' else self.SKU_UNIT_MAP_GOLD
        for _, ln in iter_nearby_lines(lines, idx, window=4):
            m = _SKU_PATTERN.search(ln)
            if m and m.group(1) in sku_map:
                return sku_map[m.group(1)]
        return None


# =============================================================================
# Costco Parser
# =============================================================================

class CostcoParser(VendorParser):
    """Parser for Costco precious metals emails."""

    name = "Costco"
    SKU_BUNDLE_MAP: Dict[str, float] = {'3796875': 25.0}

    def matches_sender(self, from_header: str) -> bool:
        return 'costco' in (from_header or '').lower()

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        items, lines = extract_basic_line_items(text)

        for item in items:
            if item.qty == 1.0:
                eq = find_qty_near(lines, item.idx)
                if eq:
                    item.qty = eq
                elif 0.98 <= item.unit_oz <= 1.02:
                    bq = find_bundle_qty(lines, item.idx, self.SKU_BUNDLE_MAP)
                    if bq:
                        item.qty = bq

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        hit = extract_price_from_lines(lines, idx, metal, unit_oz)
        return PriceHit(amount=hit.amount, kind='unit') if hit else None


# =============================================================================
# Royal Canadian Mint (RCM) Parser
# =============================================================================

class RCMParser(VendorParser):
    """Parser for Royal Canadian Mint emails."""

    name = "RCM"

    # Subject classification for email priority (exposed for external use)
    SUBJECT_RANK = {'confirmation': 3, 'shipping': 2, 'request': 1, 'other': 0}

    # Subject classification patterns: (keywords, type, priority)
    _SUBJECT_CLASSIFIERS = [
        (('confirmation for order number', 'confirmation for order'), 'confirmation', 3),
        (('shipping confirmation', 'was shipped'), 'shipping', 2),
        (('we received your request',), 'request', 1),
    ]

    # RCM-specific patterns (more flexible for their email format)
    _PAT_TENTH_OZ = re.compile(r"(?i)\b1\s*/\s*10\s*[- ]?oz\b")
    _PAT_FRAC = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b")
    _PAT_OZ = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*[- ]?oz\b")
    _PAT_GRAMS = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b")

    # RCM-specific banned terms (includes Canadian taxes)
    _PRICE_BAN = re.compile(
        r"(?i)(subtotal|shipping|handling|tax|gst|hst|pst|savings|"
        r"free\s+shipping|orders?\s+over|threshold)"
    )

    def matches_sender(self, from_header: str) -> bool:
        email = (from_header or '').lower()
        return any(x in email for x in ('email.mint.ca', 'mint.ca', 'royalcanadianmint.ca'))

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        """Extract line items with RCM-specific patterns."""
        t = normalize_unicode(text or '')
        lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]
        items: List[LineItem] = []
        metal_guess = infer_metal_from_context(text) or 'gold'

        for idx, ln in enumerate(lines):
            metal = infer_metal_from_context(ln) or metal_guess
            qty = find_qty_near(lines, idx, window=7) or 1.0

            # 1/10-oz special case
            if self._PAT_TENTH_OZ.search(ln):
                items.append(LineItem(metal=metal, unit_oz=0.1, qty=qty, idx=idx))
                continue

            # Extract weights using pattern matching
            for oz in self._extract_weights(ln):
                items.append(LineItem(metal=metal, unit_oz=oz, qty=qty, idx=idx))

        return dedupe_line_items(items), lines

    def _extract_weights(self, ln: str) -> List[float]:
        """Extract all weight values (in oz) from a line."""
        weights: List[float] = []
        for m in self._PAT_FRAC.finditer(ln):
            try:
                weights.append(float(m.group(1)) / max(float(m.group(2) or 1), 1.0))
            except (ValueError, IndexError):
                continue
        for m in self._PAT_OZ.finditer(ln):
            try:
                weights.append(float(m.group(1)))
            except (ValueError, IndexError):
                continue
        for m in self._PAT_GRAMS.finditer(ln):
            try:
                weights.append(float(m.group(1)) / G_PER_OZ)
            except (ValueError, IndexError):
                continue
        return weights

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Find price near item with RCM-specific filtering (prefers 'total' lines)."""
        lb, ub = get_price_band(metal, unit_oz)
        best: Dict[str, Tuple[float, int]] = {}  # kind -> (amount, distance)

        for d, ln in iter_nearby_lines(lines, idx, window=21, forward_only=True):
            if self._PRICE_BAN.search(ln.lower()):
                continue
            for m in MONEY_PATTERN.finditer(ln):
                try:
                    amt = float(m.group(2).replace(",", ""))
                except (ValueError, IndexError):
                    continue
                if metal == 'gold' and not (lb <= amt <= ub):
                    continue
                dist = abs(d - idx)
                kind = 'total' if re.search(r"(?i)\btotal\b", ln) else 'unit'
                if kind not in best or dist < best[kind][1]:
                    best[kind] = (amt, dist)

        for kind in ('total', 'unit'):
            if kind in best:
                return PriceHit(amount=best[kind][0], kind=kind)
        return None

    def classify_email(self, subject: str) -> Tuple[str, int]:
        """Classify RCM email by subject for priority ranking."""
        s = (subject or '').lower()
        for keywords, email_type, priority in self._SUBJECT_CLASSIFIERS:
            if any(kw in s for kw in keywords):
                return (email_type, priority)
        return ('other', 0)

    def extract_order_id(self, subject: str, body: str) -> Optional[str]:
        """Extract RCM order ID (PO number) from subject or body."""
        m = re.search(r"(?i)\bPO\d{5,}\b", subject or "") or \
            re.search(r"(?i)\bPO\d{5,}\b", body or "")
        return m.group(0) if m else None

    def extract_confirmation_totals(self, text: str) -> List[float]:
        """Extract per-item 'Total $X CAD' amounts from confirmation email."""
        t = (text or '').replace('\u00A0', ' ')
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        amounts: List[float] = []

        pat = re.compile(
            r"(?i)\btotal\b[^\n]*?(?:C\$|CAD\s*\$|CAD\$|\$)\s*"
            r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))\s*CAD"
        )
        ban = re.compile(r"(?i)(orders?\s+over|threshold|free\s+shipping|subtotal|savings)")

        for ln in lines:
            if ban.search(ln or ''):
                continue
            m = pat.search(ln or '')
            if m:
                try:
                    val = float((m.group(1) or '0').replace(',', ''))
                    amounts.append(val)
                except (ValueError, IndexError):
                    continue
        return amounts


# =============================================================================
# Vendor Registry
# =============================================================================

# All available vendor parsers
ALL_VENDORS: List[VendorParser] = [TDParser(), CostcoParser(), RCMParser()]

# Gmail uses all vendors
GMAIL_VENDORS: List[VendorParser] = ALL_VENDORS

# Outlook currently only uses RCM
OUTLOOK_VENDORS: List[VendorParser] = [RCMParser()]


def get_vendor_for_sender(from_header: str, vendors: List[VendorParser] = ALL_VENDORS) -> Optional[VendorParser]:
    """Get the appropriate vendor parser for an email sender."""
    for vendor in vendors:
        if vendor.matches_sender(from_header):
            return vendor
    return None


__all__ = [
    'LineItem',
    'PriceHit',
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
