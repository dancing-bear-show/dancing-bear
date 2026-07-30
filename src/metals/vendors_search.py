"""Vendor registry and lookup helpers."""
from __future__ import annotations

from typing import List, Optional

from .vendors_parse import VendorParser, TDParser, CostcoParser, RCMParser

# All available vendor parsers
ALL_VENDORS: List[VendorParser] = [TDParser(), CostcoParser(), RCMParser()]

# Gmail uses all vendors
GMAIL_VENDORS: List[VendorParser] = ALL_VENDORS

# Outlook currently only uses RCM
OUTLOOK_VENDORS: List[VendorParser] = [RCMParser()]


def get_vendor_for_sender(
    from_header: str, vendors: List[VendorParser] = ALL_VENDORS
) -> Optional[VendorParser]:
    """Get the appropriate vendor parser for an email sender."""
    for vendor in vendors:
        if vendor.matches_sender(from_header):
            return vendor
    return None
