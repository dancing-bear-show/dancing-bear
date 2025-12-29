"""Vendor-specific parsers for precious metals email extraction."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode

from .costs_common import G_PER_OZ, MONEY_PATTERN, get_price_band


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
        pass  # Abstract method

    @abstractmethod
    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        """Extract line items from email text. Returns (items, lines)."""
        pass  # Abstract method

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

# Common regex patterns for line item extraction
PAT_FRAC_OZ = re.compile(
    r"(?i)\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)
PAT_DECIMAL_OZ = re.compile(
    r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*[- ]?oz\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)
PAT_GRAMS = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b[^\n]*?\b(gold|silver)\b"
    r"(?:(?:(?!\n).)*?\bx\s*(\d+))?"
)

# Quantity detection patterns
QTY_PATTERNS = [
    re.compile(r"(?i)\bqty\s*[:#]?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bquantity\s*[:#]?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bx\s*(\d{1,3})\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*x\b"),
]


def find_qty_near(lines: List[str], idx: int, window: int = 4) -> Optional[float]:
    """Find explicit quantity near a line index."""
    checked: set[int] = set()
    for d in range(window):
        for j in {idx + d, idx - d}:  # Set dedupes when d=0
            if j in checked or not (0 <= j < len(lines)):
                continue
            checked.add(j)
            for pat in QTY_PATTERNS:
                m = pat.search(lines[j] or "")
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


def extract_basic_line_items(text: str) -> Tuple[List[LineItem], List[str]]:
    """Basic line item extraction shared across vendors."""
    items: List[LineItem] = []
    t = normalize_unicode(text or '')
    lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]

    for idx, ln in enumerate(lines):
        # Fractional ounces (e.g., 1/10 oz gold)
        for m in PAT_FRAC_OZ.finditer(ln):
            try:
                num = float(m.group(1))
                den = float(m.group(2) or 1)
                metal = (m.group(3) or '').lower()
                qty = float(m.group(4) or 1)
                unit_oz = num / max(den, 1.0)
                items.append(LineItem(metal=metal, unit_oz=unit_oz, qty=qty, idx=idx))
            except (ValueError, IndexError):
                continue  # Skip malformed matches

        # Decimal ounces (e.g., 1 oz silver)
        for m in PAT_DECIMAL_OZ.finditer(ln):
            try:
                unit_oz = float(m.group(1))
                metal = (m.group(2) or '').lower()
                qty = float(m.group(3) or 1)
                items.append(LineItem(metal=metal, unit_oz=unit_oz, qty=qty, idx=idx))
            except (ValueError, IndexError):
                continue  # Skip malformed matches

        # Grams (e.g., 31g gold)
        for m in PAT_GRAMS.finditer(ln):
            try:
                wt_g = float(m.group(1))
                metal = (m.group(3) or '').lower()
                qty = float(m.group(4) or 1)
                unit_oz = wt_g / G_PER_OZ
                items.append(LineItem(metal=metal, unit_oz=unit_oz, qty=qty, idx=idx))
            except (ValueError, IndexError):
                continue  # Skip malformed matches

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

        # Apply TD-specific quantity heuristics
        for item in items:
            if item.qty == 1.0:
                # Check for explicit quantity near the line
                eq = find_qty_near(lines, item.idx)
                if eq:
                    item.qty = eq
                else:
                    # Check for bundle indicators
                    bq = self._find_bundle_qty(lines, item.idx)
                    if bq and 0.98 <= item.unit_oz <= 1.02:
                        item.qty = bq

            # Check for unit oz overrides
            uov = self._get_unit_oz_override(lines, item.idx, item.metal)
            if uov:
                item.unit_oz = uov

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Extract price near item with TD-specific logic."""
        ban = re.compile(r"(?i)\b(subtotal|shipping|tax|order number|order #)\b")
        lb, ub = get_price_band(metal, unit_oz)

        for d in range(13):
            for j in {idx + d, idx - d}:  # Set dedupes when d=0
                if not (0 <= j < len(lines)):
                    continue
                ln = lines[j] or ""
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

                # Determine kind
                low = ln.lower()
                if re.search(r"(?i)\b(unit|each|ea|per)\b", low):
                    return PriceHit(amount=amt, kind='unit')
                if re.search(r"(?i)\btotal\b", low):
                    return PriceHit(amount=amt, kind='total')
                return PriceHit(amount=amt, kind='unknown')

        return None

    def _extract_email(self, from_header: str) -> str:
        m = re.search(r"<([^>]+)>", from_header or '')
        return m.group(1) if m else (from_header or '')

    def _find_bundle_qty(self, lines: List[str], idx: int) -> Optional[float]:
        """Find bundle quantity indicators."""
        pats = [
            re.compile(r"(?i)\b(\d{1,3})\s*[- ]?pack\b"),
            re.compile(r"(?i)\bpack\s*of\s*(\d{1,3})\b"),
            re.compile(r"(?i)\b(\d{1,3})\s*coins?\b"),
            re.compile(r"(?i)\b(\d{1,3})\s*ct\b"),
            re.compile(r"(?i)\b(roll|tube)\s*of\s*(\d{1,3})\b"),
        ]
        checked: set[int] = set()
        for d in range(4):
            for j in {idx + d, idx - d}:  # Set dedupes when d=0
                if j in checked or not (0 <= j < len(lines)):
                    continue
                checked.add(j)
                s = lines[j]
                for pat in pats:
                    m = pat.search(s or "")
                    if m:
                        group_count = len(m.groups())
                        for g in (1, 2):
                            if g <= group_count:
                                val = m.group(g)
                                if val and val.isdigit():
                                    n = int(val)
                                    if 2 <= n <= 200:
                                        return float(n)
                # SKU mapping
                m_item = re.search(r"(?i)\bitem(?:\s*(?:#|number)\s*)?:?\s*(\d{5,})\b", s or '')
                if m_item:
                    sku = m_item.group(1)
                    if sku in self.SKU_BUNDLE_MAP:
                        return self.SKU_BUNDLE_MAP[sku]
        return None

    def _get_unit_oz_override(self, lines: List[str], idx: int, metal: str) -> Optional[float]:
        """Get unit oz override from SKU or phrase mapping."""
        sku_map = self.SKU_UNIT_MAP_SILVER if metal == 'silver' else self.SKU_UNIT_MAP_GOLD
        for d in range(4):
            for j in {idx + d, idx - d}:  # Set dedupes when d=0
                if 0 <= j < len(lines):
                    m = re.search(r"(?i)\bitem(?:\s*(?:#|number)\s*)?:?\s*(\d{5,})\b", lines[j] or '')
                    if m and m.group(1) in sku_map:
                        return sku_map[m.group(1)]
        return None


# =============================================================================
# Costco Parser
# =============================================================================

class CostcoParser(VendorParser):
    """Parser for Costco precious metals emails."""

    name = "Costco"

    SKU_BUNDLE_MAP: Dict[str, float] = {
        '3796875': 25.0,
    }

    def matches_sender(self, from_header: str) -> bool:
        return 'costco' in (from_header or '').lower()

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        items, lines = extract_basic_line_items(text)

        # Apply Costco-specific quantity heuristics
        for item in items:
            if item.qty == 1.0:
                eq = find_qty_near(lines, item.idx)
                if eq:
                    item.qty = eq
                else:
                    bq = self._find_bundle_qty(lines, item.idx)
                    if bq and 0.98 <= item.unit_oz <= 1.02:
                        item.qty = bq

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Extract price with Costco-specific heuristics."""
        ban = re.compile(r"(?i)\b(subtotal|shipping|tax|order number|order #)\b")
        lb, ub = get_price_band(metal, unit_oz)

        for d in range(13):
            for j in {idx + d, idx - d}:  # Set dedupes when d=0
                if not (0 <= j < len(lines)):
                    continue
                ln = lines[j] or ""
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

                # Costco often shows unit price next to 'x N'
                return PriceHit(amount=amt, kind='unit')

        return None

    def _find_bundle_qty(self, lines: List[str], idx: int) -> Optional[float]:
        """Find bundle quantity from SKU or text patterns."""
        for d in range(4):
            for j in {idx + d, idx - d}:  # Set dedupes when d=0
                if 0 <= j < len(lines):
                    s = lines[j] or ''
                    m = re.search(r"(?i)\bitem(?:\s*(?:#|number)\s*)?:?\s*(\d{5,})\b", s)
                    if m and m.group(1) in self.SKU_BUNDLE_MAP:
                        return self.SKU_BUNDLE_MAP[m.group(1)]
        return None


# =============================================================================
# Royal Canadian Mint (RCM) Parser
# =============================================================================

class RCMParser(VendorParser):
    """Parser for Royal Canadian Mint emails."""

    name = "RCM"

    # Subject classification for email priority
    SUBJECT_RANK = {'confirmation': 3, 'shipping': 2, 'request': 1, 'other': 0}

    def matches_sender(self, from_header: str) -> bool:
        email = (from_header or '').lower()
        return any(x in email for x in ('email.mint.ca', 'mint.ca', 'royalcanadianmint.ca'))

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        """Extract line items with RCM-specific patterns."""
        t = normalize_unicode(text or '')
        lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]
        items: List[LineItem] = []

        # RCM patterns - more flexible for their email format
        pat_tenth_oz = re.compile(r"(?i)\b1\s*/\s*10\s*[- ]?oz\b")
        pat_frac = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b")
        pat_oz = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*[- ]?oz\b")
        pat_g = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b")

        metal_guess = infer_metal_from_context(text) or 'gold'

        for idx, ln in enumerate(lines):
            # 1/10-oz special case
            if pat_tenth_oz.search(ln):
                metal = infer_metal_from_context(ln) or metal_guess
                qty = find_qty_near(lines, idx, window=7) or 1.0
                items.append(LineItem(metal=metal, unit_oz=0.1, qty=qty, idx=idx))
                continue

            # General fractional oz
            for m in pat_frac.finditer(ln):
                try:
                    num = float(m.group(1))
                    den = float(m.group(2) or 1)
                    oz = num / max(den, 1.0)
                    metal = infer_metal_from_context(ln) or metal_guess
                    qty = find_qty_near(lines, idx, window=7) or 1.0
                    items.append(LineItem(metal=metal, unit_oz=oz, qty=qty, idx=idx))
                except (ValueError, IndexError):
                    continue

            # Decimal oz
            for m in pat_oz.finditer(ln):
                try:
                    oz = float(m.group(1))
                    metal = infer_metal_from_context(ln) or metal_guess
                    qty = find_qty_near(lines, idx, window=7) or 1.0
                    items.append(LineItem(metal=metal, unit_oz=oz, qty=qty, idx=idx))
                except (ValueError, IndexError):
                    continue

            # Grams
            for m in pat_g.finditer(ln):
                try:
                    wt_g = float(m.group(1))
                    metal = infer_metal_from_context(ln) or metal_guess
                    qty = find_qty_near(lines, idx, window=7) or 1.0
                    items.append(LineItem(metal=metal, unit_oz=wt_g / G_PER_OZ, qty=qty, idx=idx))
                except (ValueError, IndexError):
                    continue

        return dedupe_line_items(items), lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Find price near item with RCM-specific filtering."""
        ban = re.compile(
            r"(?i)(subtotal|shipping|handling|tax|gst|hst|pst|savings|"
            r"free\s+shipping|orders?\s+over|threshold)"
        )
        lb, ub = get_price_band(metal, unit_oz)

        best_total: Optional[Tuple[float, int]] = None
        best_unit: Optional[Tuple[float, int]] = None

        for d in range(21):
            j = idx + d
            if not (0 <= j < len(lines)):
                continue
            ln = lines[j] or ""
            if ban.search(ln.lower()):
                continue

            for m in MONEY_PATTERN.finditer(ln):
                try:
                    amt = float(m.group(2).replace(",", ""))
                except (ValueError, IndexError):
                    continue

                # Filter by price band for gold
                if metal == 'gold' and not (lb <= amt <= ub):
                    continue

                if re.search(r"(?i)\btotal\b", ln):
                    if best_total is None or d < best_total[1]:
                        best_total = (amt, d)
                else:
                    if best_unit is None or d < best_unit[1]:
                        best_unit = (amt, d)

        if best_total:
            return PriceHit(amount=best_total[0], kind='total')
        if best_unit:
            return PriceHit(amount=best_unit[0], kind='unit')
        return None

    def classify_email(self, subject: str) -> Tuple[str, int]:
        """Classify RCM email by subject for priority ranking."""
        s = (subject or '').lower()
        if 'confirmation for order number' in s or 'confirmation for order' in s:
            return ('confirmation', self.SUBJECT_RANK['confirmation'])
        if 'shipping confirmation' in s or 'was shipped' in s:
            return ('shipping', self.SUBJECT_RANK['shipping'])
        if 'we received your request' in s:
            return ('request', self.SUBJECT_RANK['request'])
        return ('other', self.SUBJECT_RANK['other'])

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
    'infer_metal_from_context',
]
