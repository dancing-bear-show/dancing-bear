from __future__ import annotations

import os
import re
from typing import Any

from core.secrets import is_sensitive_key
from core.token_shapes import contains_token_shape

# Key substrings shield masks on top of core.secrets.is_sensitive_key. These are
# deliberately broader than core's rules (a bare "key" substring masks
# "sort_key" too): this output is a human-facing config dump, where a false
# positive costs a redacted id and a false negative leaks a credential.
# Longer spellings ("api_key", "access_token", "client_secret", ...) are
# omitted because one of these substrings already matches them.
SECRET_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "authorization",
    "bearer",
    "key",
)


def _is_secret_key(key: str) -> bool:
    """Return True when either core's rules or shield's substrings flag `key`."""
    k = key.lower()
    return is_sensitive_key(k) or any(s in k for s in SECRET_KEY_SUBSTRINGS)


def _mask_str(v: str, *, head: int = 4, tail: int = 4) -> str:
    n = len(v)
    if n <= head + tail:
        return "***"
    return f"{v[:head]}…{v[-tail:]} (len={n})"


# Looser shapes shield masks on top of core.token_shapes: shorter or
# non-vendor look-alikes (ghp_ under 36, AIza under 34, sk-live-/sk-test-).
# A display mask should never narrow -- over-masking a config dump costs
# nothing, under-masking can show a truncated real secret. Kept here, not in
# the shared catalog, so memory export's block/warn policy is unaffected.
_LOOSE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bglsa_[A-Z0-9]{20,}\b", re.I),
    re.compile(r"\bxox[abpisr]-[A-Z0-9-]{10,}\b", re.I),
    re.compile(r"\bsk-(?:live|test|proj)-[A-Z0-9_-]{16,}\b", re.I),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\bAIza[A-Z0-9_-]{20,}\b", re.I),
    re.compile(r"eyJ[A-Za-z0-9_=-]{10,}\.[A-Za-z0-9_=-]{10,}\.[A-Za-z0-9_=-]{8,}"),
)


def _contains_secretish_value(v: str) -> bool:
    """Return True when `v` holds a catalog token shape or a shield-local loose one."""
    text = v or ""
    return contains_token_shape(text) or any(p.search(text) for p in _LOOSE_VALUE_PATTERNS)


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
    secretish = _is_secret_key(k) and k != "client_id"
    if secretish or _contains_secretish_value(v):
        return _mask_str(v)

    # Mildly sensitive ids: client_id
    if k == "client_id" or k.endswith("_client_id"):
        return _mask_str(v)

    return v


def shield_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    """Return a shallow-copied dict with masked values for known secret keys."""
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        try:
            if isinstance(v, str):
                out[k] = mask_value(str(k), v)
            else:
                out[k] = v
        except Exception:
            out[k] = v
    return out
