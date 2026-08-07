"""Location string parsing helpers for Outlook Graph API events."""

from __future__ import annotations

import re
from typing import Any


def _split_name_and_addr(s: str) -> tuple[str, str]:
    """Split a location string into (name, address) pair."""
    if "(" in s and ")" in s:
        try:
            nm, rest = s.split("(", 1)
            addr = rest.rsplit(")", 1)[0]
            return nm.strip(), addr.strip()
        except Exception:  # nosec B110 - malformed parens, try other patterns
            pass
    if " at " in s:
        head, addr = s.rsplit(" at ", 1)
        return head.strip(), addr.strip()
    m = re.search(r"\b\d+\b", s)
    if m:
        return s[:m.start()].strip(), s[m.start():].strip()
    return s.strip(), ""


def _is_word_city(w: str) -> bool:
    """Return True if word looks like a city name part (alpha, no digits)."""
    return any(ch.isalpha() for ch in w) and not any(ch.isdigit() for ch in w)


def _looks_like_state_postal(toks: list[str]) -> bool:
    """Return True if toks[0] is a 2-letter state and the rest is a postal code."""
    if len(toks) < 2 or not re.match(r"^[A-Z]{2}$", toks[0]):
        return False
    rest = (" ".join(toks[1:])).upper()
    return bool(re.match(r"^[A-Z]\d[A-Z]$|^[A-Z]\d[A-Z]\s\d[A-Z]\d$", rest))


def _city_and_street_from_words(words: list[str], street: str) -> tuple[str, str]:
    """Peel trailing city-name words off the street tokens.

    Returns (city, street).
    """
    if len(words) >= 2 and _is_word_city(words[-1]) and _is_word_city(words[-2]):
        return f"{words[-2]} {words[-1]}", " ".join(words[:-2]) or street
    if words and _is_word_city(words[-1]):
        return words[-1], " ".join(words[:-1]) or street
    return "", street


def _parse_addr_two_parts(parts: list[str], street: str) -> tuple[str, str, str, str]:
    """Parse city/state/postal from a two-part address.

    Returns (city, state, postal, street).
    """
    toks = parts[1].split()
    if not _looks_like_state_postal(toks):
        return parts[1], "", "", street

    state = toks[0]
    rest = " ".join(toks[1:]).upper()
    mpc = re.search(r"[A-Z]\d[A-Z]\s?\d[A-Z]\d", rest)
    postal = rest[mpc.start():mpc.end()] if mpc else ""
    words = [w for w in parts[0].strip().split() if w]
    city, street = _city_and_street_from_words(words, street)
    return city, state, postal, street


def _split_canada_postal(toks: list[str]) -> tuple[str, list[str]]:
    """Peel a trailing Canadian postal code pair off toks.

    Returns (postal, remaining_toks).
    """
    if len(toks) < 2:
        return "", toks
    pair = (toks[-2] + " " + toks[-1]).upper()
    if re.match(r"^[A-Z]\d[A-Z]\s\d[A-Z]\d$", pair):
        return pair, toks[:-2]
    return "", toks


def _find_state_token(toks: list[str]) -> str:
    """Return the last two-letter alpha token in toks, or ''."""
    state = ""
    for t in toks:
        tt = t.strip().strip(",")
        if len(tt) == 2 and tt.isalpha():
            state = tt
    return state


def _find_postal_token(toks: list[str]) -> str:
    """Return the last token containing a digit, or ''."""
    return next((t for t in reversed(toks) if any(ch.isdigit() for ch in t)), "")


def _parse_addr_multi_parts(parts: list[str]) -> tuple[str, str, str, str]:
    """Parse city/state/postal/country from 3+ part address.

    Returns (city, state, postal, country).
    """
    city = parts[-2]
    postal, toks = _split_canada_postal(parts[-1].split())
    state = _find_state_token(toks)
    postal = postal or _find_postal_token(toks)
    country = parts[-1] if len(parts) >= 4 else ""
    return city, state, postal, country


def _parse_addr_parts(parts: list[str], street: str) -> tuple[str, str, str, str, str]:
    """Dispatch to two-part or multi-part address parser.

    Returns (street, city, state, postal, country).
    """
    city = state = postal = country = ""
    if len(parts) == 2:
        city, state, postal, street = _parse_addr_two_parts(parts, street)
    elif len(parts) >= 3:
        city, state, postal, country = _parse_addr_multi_parts(parts)
    return street, city, state, postal, country


def _parse_addr(addr: str) -> dict[str, Any]:
    """Parse an address string into a structured dict for Graph API."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    street = parts[0] if parts else ""
    street, city, state, postal, country = _parse_addr_parts(parts, street)
    addr_obj: dict[str, Any] = {}
    for key, val in [("street", street), ("city", city), ("state", state),
                     ("postalCode", postal), ("countryOrRegion", country)]:
        if val:
            addr_obj[key] = val
    return addr_obj


def _parse_location(loc: str) -> dict[str, Any]:
    """Parse a location string into Outlook location with structured address when possible."""
    disp = (loc or "").strip()
    name, addr = _split_name_and_addr(disp)
    if addr:
        try:
            addr_obj = _parse_addr(addr)
        except Exception:  # nosec B110 - malformed address, skip structured parsing
            addr_obj = {}
    else:
        addr_obj = {}

    loc_obj: dict[str, Any] = {"displayName": name or disp}
    if addr_obj:
        loc_obj["address"] = addr_obj
    return loc_obj


def _normalize_days(days: list[str]) -> list[str]:
    """Map MO,TU,WE,TH,FR,SA,SU -> monday,tuesday,... as Graph expects."""
    from core.date_utils import RRULE_CODE_TO_DAY_NAME

    out: list[str] = []
    for d in days:
        if not d:
            continue
        dd = d.strip()
        if len(dd) == 2:
            out.append(RRULE_CODE_TO_DAY_NAME.get(dd.upper(), dd.lower()))
        else:
            out.append(dd.lower())
    seen: set[str] = set()
    uniq: list[str] = []
    for d in out:
        if d not in seen:
            uniq.append(d)
            seen.add(d)
    return uniq
