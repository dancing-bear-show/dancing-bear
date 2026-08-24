"""Sender address parsing and protected-sender matching."""

from __future__ import annotations

from core.text_utils import extract_email_address


def extract_sender_email(from_val: str) -> str:
    """Return the bare lowercased address from a From-like header value."""
    return extract_email_address(from_val or "").strip()


def extract_domain(email: str) -> str:
    """Return the lowercased domain part of an address, or the input if unparseable."""
    normalized = (email or "").lower().strip()
    return normalized.split("@")[-1] if "@" in normalized else normalized


def matches_protected_pattern(email: str, domain: str, pattern: str) -> bool:
    """Return True if email/domain matches a single protected pattern.

    A pattern starting with '@' matches a whole domain; otherwise it is an
    exact address match.
    """
    if pattern.startswith("@"):
        return email.endswith(pattern) or domain == pattern.lstrip("@")
    return pattern == email


def is_protected_email(email: str, protected_patterns: list[str]) -> bool:
    """Return True if an already-extracted address matches any protected pattern."""
    domain = extract_domain(email)
    return any(
        matches_protected_pattern(email, domain, p)
        for p in protected_patterns
        if p
    )


def is_protected_sender(from_val: str, protected_patterns: list[str]) -> bool:
    """Return True if a raw From header value matches any protected pattern."""
    return is_protected_email(extract_sender_email(from_val), protected_patterns)
