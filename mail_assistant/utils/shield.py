from __future__ import annotations

from typing import Any, Dict, Iterable
import os
import re


# Heuristic key substrings that imply secret values when present in key names
SECRET_KEYS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "access_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "bearer",
    "key",
)

# Heuristic patterns that imply secret values even if key name is generic
# Borrowed/adapted from cars-sre-utils secret shielding conventions
SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub personal access token
    re.compile(r"\bglsa_[A-Za-z0-9]{20,}\b", re.I),  # Grafana service account token
    re.compile(r"\bxox[abpisr]-[A-Za-z0-9-]{10,}\b", re.I),  # Slack tokens
    re.compile(r"\bapi-[A-Za-z0-9]{16,}\b", re.I),  # API tokens like LaunchDarkly
    re.compile(r"\brootly_[A-Za-z0-9]{16,}\b", re.I),  # Rootly
    re.compile(r"\bsk-(?:live|test|proj)-[A-Za-z0-9_-]{16,}\b", re.I),  # OpenAI tokens
    re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}\b"),  # Google OAuth access token
    re.compile(r"\bAIza[0-9A-Za-z-_]{20,}\b"),  # Google API key
    # JWT-like three-part tokens
    re.compile(r"eyJ[a-zA-Z0-9_=-]{10,}\.[a-zA-Z0-9_=-]{10,}\.[a-zA-Z0-9_=-]{8,}"),
    # MSAL/Graph opaque tokens often start with 'M.' and are long
    re.compile(r"\bM\.[A-Za-z0-9._!*$-]{20,}\b"),
]


def _mask_str(v: str, *, head: int = 4, tail: int = 4) -> str:
    n = len(v)
    if n <= head + tail:
        return "***"
    return f"{v[:head]}…{v[-tail:]} (len={n})"


def _contains_secretish_value(v: str) -> bool:
    try:
        for pat in SECRET_VALUE_PATTERNS:
            if pat.search(v or ""):
                return True
    except Exception:
        return False
    return False


def mask_value(key: str, val: str) -> str:
    """Mask sensitive values for safe display.

    - File paths are shown with an existence hint.
    - Secret-like keys are redacted to head…tail with length.
    - Mildly sensitive ids (e.g., client_id) are partially masked.
    """
    k = (key or "").lower()
    v = val or ""
    # Paths: show and indicate existence
    if any(sep in v for sep in ("/", "\\")):
        try:
            exists = os.path.exists(os.path.expanduser(v))
        except Exception:
            exists = False
        return f"{v} (exists: {'yes' if exists else 'no'})"

    # Secret-ish keys (excluding client_id)
    secretish = any(s in k for s in SECRET_KEYS) and k != "client_id"
    if secretish or _contains_secretish_value(v):
        return _mask_str(v)

    # Mildly sensitive ids: client_id
    if k == "client_id" or k.endswith("_client_id"):
        return _mask_str(v)

    return v


def shield_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow-copied dict with masked values for known secret keys."""
    out: Dict[str, Any] = {}
    for k, v in (data or {}).items():
        try:
            if isinstance(v, str):
                out[k] = mask_value(str(k), v)
            else:
                out[k] = v
        except Exception:
            out[k] = v
    return out
