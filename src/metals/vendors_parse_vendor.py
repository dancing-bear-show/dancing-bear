"""Vendor-specific parser classes for precious metals email parsing."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .constants import (
    G_PER_OZ,
    MONEY_PATTERN,
    PAT_SKU,
    PRICE_BAN_RCM,
    SKU_UNIT_MAP_SILVER,
    SKU_UNIT_MAP_GOLD,
)
from .costs_common import get_price_band
from .vendors_parse_core import (
    LineItem,
    PriceHit,
    PriceSearchContext,
    _PAT_TOTAL,
    dedupe_line_items,
    extract_basic_line_items,
    extract_price_from_lines,
    find_qty_near,
    infer_metal_from_context,
    iter_nearby_lines,
    _enhance_item_qty,
)


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
# TD Precious Metals Parser
# =============================================================================

class TDParser(VendorParser):
    """Parser for TD Precious Metals emails."""

    name = "TD"

    def matches_sender(self, from_header: str) -> bool:
        email = self._extract_email(from_header).lower()
        return any(x in email for x in ('td.com', 'tdsecurities.com', 'preciousmetals.td.com'))

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        items, lines = extract_basic_line_items(text)

        for item in items:
            _enhance_item_qty(item, lines, check_bundle=True)

            # TD-specific: Check for SKU-based unit oz override
            uov = self._get_unit_oz_override(lines, item.idx, item.metal)
            if uov:
                item.unit_oz = uov

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        ctx = PriceSearchContext(lines=lines, idx=idx, metal=metal, unit_oz=unit_oz)
        return extract_price_from_lines(ctx)

    def _extract_email(self, from_header: str) -> str:
        m = re.search(r"<([^>]+)>", from_header or '')
        return m.group(1) if m else (from_header or '')

    def _get_unit_oz_override(
        self, lines: List[str], idx: int, metal: str
    ) -> Optional[float]:
        """Get unit oz override from SKU mapping."""
        sku_map = SKU_UNIT_MAP_SILVER if metal == 'silver' else SKU_UNIT_MAP_GOLD
        for _, ln in iter_nearby_lines(lines, idx, window=4):
            m = PAT_SKU.search(ln)
            if m and m.group(1) in sku_map:
                return sku_map[m.group(1)]
        return None


# =============================================================================
# Costco Parser
# =============================================================================

class CostcoParser(VendorParser):
    """Parser for Costco precious metals emails."""

    name = "Costco"

    def matches_sender(self, from_header: str) -> bool:
        return 'costco' in (from_header or '').lower()

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        items, lines = extract_basic_line_items(text)

        for item in items:
            _enhance_item_qty(item, lines, check_bundle=True)

        return items, lines

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        ctx = PriceSearchContext(lines=lines, idx=idx, metal=metal, unit_oz=unit_oz)
        hit = extract_price_from_lines(ctx)
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

    # RCM-specific banned terms - use imported constant
    _PRICE_BAN = PRICE_BAN_RCM

    def matches_sender(self, from_header: str) -> bool:
        email = (from_header or '').lower()
        return any(x in email for x in ('email.mint.ca', 'mint.ca', 'royalcanadianmint.ca'))

    def _extract_line_items_from_text(
        self, lines: List[str], metal_guess: str
    ) -> List[LineItem]:
        """Extract all line items from text lines."""
        items: List[LineItem] = []

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

        return items

    def extract_line_items(self, text: str) -> Tuple[List[LineItem], List[str]]:
        """Extract line items with RCM-specific patterns."""
        from core.text_utils import normalize_unicode
        t = normalize_unicode(text or '')
        lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]
        metal_guess = infer_metal_from_context(text) or 'gold'

        items = self._extract_line_items_from_text(lines, metal_guess)
        return dedupe_line_items(items), lines

    @staticmethod
    def _weight_from_frac_match(m: re.Match) -> float:
        """Convert a fractional-oz match ('1/2 oz') to ounces."""
        return float(m.group(1)) / max(float(m.group(2) or 1), 1.0)

    @staticmethod
    def _weight_from_oz_match(m: re.Match) -> float:
        """Convert a decimal-oz match ('1.5 oz') to ounces."""
        return float(m.group(1))

    @staticmethod
    def _weight_from_grams_match(m: re.Match) -> float:
        """Convert a grams match ('31.1 g') to ounces."""
        return float(m.group(1)) / G_PER_OZ

    def _collect_weights(self, ln: str, pattern: re.Pattern, to_oz) -> List[float]:
        """Run pattern over ln, converting each match to ounces via to_oz. Skips unparsable matches."""
        found: List[float] = []
        for m in pattern.finditer(ln):
            try:
                found.append(to_oz(m))
            except (ValueError, IndexError):
                continue
        return found

    def _extract_weights(self, ln: str) -> List[float]:
        """Extract all weight values (in oz) from a line."""
        weights: List[float] = []
        weights.extend(self._collect_weights(ln, self._PAT_FRAC, self._weight_from_frac_match))
        weights.extend(self._collect_weights(ln, self._PAT_OZ, self._weight_from_oz_match))
        weights.extend(self._collect_weights(ln, self._PAT_GRAMS, self._weight_from_grams_match))
        return weights

    def _is_price_in_range(self, amt: float, metal: str, unit_oz: float) -> bool:
        """Check if price is within expected range for gold."""
        if metal != 'gold':
            return True
        lb, ub = get_price_band(metal, unit_oz)
        return lb <= amt <= ub

    @dataclass
    class _CandidateContext:
        """Context for price candidate evaluation."""
        idx: int
        metal: str
        unit_oz: float

    def _update_best_candidate(
        self, best: Dict[str, Tuple[float, int]], ln: str, d: int, ctx: '_CandidateContext'
    ) -> None:
        """Update best price candidates dict from a single line."""
        for m in MONEY_PATTERN.finditer(ln):
            try:
                amt = float(m.group(2).replace(",", ""))
            except (ValueError, IndexError):
                continue
            if not self._is_price_in_range(amt, ctx.metal, ctx.unit_oz):
                continue
            dist = abs(d - ctx.idx)
            kind = 'total' if _PAT_TOTAL.search(ln) else 'unit'
            if kind not in best or dist < best[kind][1]:
                best[kind] = (amt, dist)

    def _extract_price_candidates(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Dict[str, Tuple[float, int]]:
        """Extract all price candidates near idx, ranked by distance."""
        best: Dict[str, Tuple[float, int]] = {}
        ctx = self._CandidateContext(idx=idx, metal=metal, unit_oz=unit_oz)
        for d, ln in iter_nearby_lines(lines, idx, window=21, forward_only=True):
            if self._PRICE_BAN.search(ln.lower()):
                continue
            self._update_best_candidate(best, ln, d, ctx)
        return best

    def extract_price_near_item(
        self, lines: List[str], idx: int, metal: str, unit_oz: float
    ) -> Optional[PriceHit]:
        """Find price near item with RCM-specific filtering (prefers 'total' lines)."""
        candidates = self._extract_price_candidates(lines, idx, metal, unit_oz)

        # Prefer 'total' over 'unit'
        for kind in ('total', 'unit'):
            if kind in candidates:
                return PriceHit(amount=candidates[kind][0], kind=kind)

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

    def _should_skip_total_line(self, ln: str) -> bool:
        """Check if line should be skipped based on banned terms."""
        ban = re.compile(r"(?i)(orders?\s+over|threshold|free\s+shipping|subtotal|savings)")
        return ban.search(ln or '') is not None

    def _extract_cad_total(self, ln: str) -> Optional[float]:
        """Extract CAD total amount from a line."""
        pat = re.compile(
            r"(?i)\btotal\b[^\n]*?(?:C\$|CAD\s*\$|CAD\$|\$)\s*"
            r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))\s*CAD"
        )
        m = pat.search(ln or '')
        if not m:
            return None

        try:
            return float((m.group(1) or '0').replace(',', ''))
        except (ValueError, IndexError):
            return None

    def extract_confirmation_totals(self, text: str) -> List[float]:
        """Extract per-item 'Total $X CAD' amounts from confirmation email."""
        t = (text or '').replace(' ', ' ')
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        amounts: List[float] = []

        for ln in lines:
            if self._should_skip_total_line(ln):
                continue

            amount = self._extract_cad_total(ln)
            if amount is not None:
                amounts.append(amount)

        return amounts
