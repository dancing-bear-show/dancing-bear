"""Pricing engine for Claude API cost calculation.

Holds the one model pricing table (``MODEL_PRICING`` and its resolver) used by
every telemetry cost path, plus the shared cost helpers. ``compute_cost`` is
called by the transcript provider; ``compute_raw_cost`` by OTel analytics
``get_all_costs``, ``get_daily_costs`` and ``get_model_performance``.

One OTel formula still reads ``get_model_pricing`` but computes cost itself:
``_process_api_request`` (``otel/analytics/prompts.py``) bills cache writes at
1x and omits cache reads; moving it onto ``compute_raw_cost`` is deferred
because it changes reported costs.

Locally-computed costs use Anthropic's public list prices. ``compute_cost``
scales the result by ``cost_multiplier`` in ``~/.claude/claudestats.json`` for
calibration against actual billed spend (default 1.0, no scaling);
``compute_raw_cost`` returns the unscaled list-price cost.

## Updating Model Pricing

1. Check official pricing at https://platform.claude.com/docs/en/about-claude/pricing
2. Update ``MODEL_PRICING`` below
3. Update ``_PRICING_FALLBACK_RULES`` for fallback matching (order matters)
4. Update ``_CACHE_READ_MULTIPLIERS`` for any model whose cache reads are not 0.1x
5. Run validation tests: make test

## Pricing Notes

- Long context (4.x models with 1M context): no premium — same price as base
- Prompt caching writes: 1.25x base input price for the 5-minute TTL, 2.0x for the
  1-hour TTL (``TokenMetrics.cache_creation_1h_tokens``)
- Prompt caching reads: 0.1x base input price, except per ``_CACHE_READ_MULTIPLIERS``
- Haiku 5.5: the table holds the rate for prompts up to 100K tokens; the higher
  long-prompt rate is not modelled
- Batch API: 50% discount on all tokens (not modelled here)
"""

from __future__ import annotations

from collections.abc import Callable

import json
import re
from dataclasses import dataclass

from telemetry.constants import CONFIG_PATH as _CONFIG_PATH

# (mtime, multiplier) cache so we don't re-read the JSON on every call.
_mult_cache: tuple[float, float] = (-1.0, 1.0)

# Model pricing (input_per_million, output_per_million) — Jul 2026.
# Source: https://platform.claude.com/docs/en/about-claude/pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-1-20250805": (15.0, 75.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    # Sonnet 5 launch pricing became standard; the planned Sep 2026 rise to (3.0, 15.0) was cancelled
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-8": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-4-7-1m": (5.0, 25.0),
    "claude-opus-4-6-1m": (5.0, 25.0),
    "claude-sonnet-4-8-1m": (3.0, 15.0),
    "claude-sonnet-4-6-1m": (3.0, 15.0),
    "claude-opus": (5.0, 25.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
}

# Key used when a model id matches neither MODEL_PRICING nor any fallback rule.
DEFAULT_PRICING_KEY = "claude-haiku-4-5"

# Cache reads cost this fraction of the input rate. Most models use 0.1x;
# keys are MODEL_PRICING keys, so fallback-matched variants inherit them.
_DEFAULT_CACHE_READ_MULTIPLIER = 0.1
_CACHE_READ_MULTIPLIERS: dict[str, float] = {
    "claude-opus-5-5": 0.05,
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
}

# Cache writes (cache_creation tokens) cost this multiple of the input rate:
# 1.25x for the default 5-minute TTL, 2.0x for the 1-hour TTL.
_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_WRITE_1H_MULTIPLIER = 2.0


def _cost_multiplier() -> float:
    """Return the configured cost multiplier, cached on config mtime."""
    global _mult_cache
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
        if mtime != _mult_cache[0]:
            with _CONFIG_PATH.open() as fh:
                raw = json.load(fh)
            m = raw.get("cost_multiplier", 1.0)
            mult = float(m) if isinstance(m, (int, float)) and float(m) > 0 else 1.0
            _mult_cache = (mtime, mult)
    except Exception:  # nosec B110 - config read failure falls back to default multiplier
        pass
    return _mult_cache[1]


def normalize_model(model_id: str) -> str:
    """Map a full model ID to a pricing tier key.

    Returns "opus", "sonnet", "haiku", "fable", "mythos", or "unknown".
    """
    lower = model_id.lower()
    for tier in ("opus", "sonnet", "haiku", "fable", "mythos"):
        if re.search(tier, lower):
            return tier
    return "unknown"


def model_tier(model_id: str) -> str:
    """Map a model ID string to a pricing tier (alias for normalize_model)."""
    return normalize_model(model_id)


@dataclass(frozen=True)
class TokenMetrics:
    """Token counts from a single Claude API call."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    # The part of cache_creation_tokens written with the 1-hour TTL (2.0x input
    # rate). The remainder is priced as 5-minute writes (1.25x).
    cache_creation_1h_tokens: int = 0


# Matches a following minor-version component ("-6", ".6"), which must not let
# "sonnet-5" match "sonnet-5-6". A date ("-20260901") or a context tag ("-1m")
# is not a minor version.
_MINOR_VERSION_RE = re.compile(r"[-.]\d{1,2}(?![\dm])")
# A "." between digits ("claude-opus-5.5") is read as the "-" separator.
_DOTTED_VERSION_RE = re.compile(r"(?<=\d)\.(?=\d)")


def _names_version(lower: str, marker: str) -> bool:
    """Return True if ``marker`` occurs in ``lower`` naming exactly that version.

    The marker must not be followed by a digit or by another minor-version
    component, so "opus-5-5" does not match "opus-5-50" and "sonnet-5" does
    not match "sonnet-5-6" (an unlisted newer minor is not priced at an older
    one's rate).
    """
    start = lower.find(marker)
    while start != -1:
        rest = lower[start + len(marker):]
        if not rest[:1].isdigit() and not _MINOR_VERSION_RE.match(rest):
            return True
        start = lower.find(marker, start + 1)
    return False


# Bare Claude Code model aliases (agent configs use ``model: opus``). Each
# tracks the current model of its family, so keep these in step with the
# newest MODEL_PRICING entries. Pricing is not event-dated: events recorded
# while an alias named an older model are priced at the current rate.
_BARE_ALIASES: dict[str, str] = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
}


# Ordered fallback rules for resolve_pricing_key(): evaluated top-to-bottom
# after exact and embedded-key matching fail. Each predicate takes the
# lowercased model id; the first match wins. Order matters — opus-5-5,
# sonnet-5 and the "1m" combos must be checked before the generic
# opus/sonnet substring checks, and fable/mythos before the haiku default.
_PRICING_FALLBACK_RULES: list[tuple[Callable[[str], bool], str]] = [
    (lambda m: _names_version(m, "opus-5-5"), "claude-opus-5-5"),
    (lambda m: _names_version(m, "sonnet-5-5"), "claude-sonnet-5-5"),
    (lambda m: _names_version(m, "haiku-5-5"), "claude-haiku-5-5"),
    (lambda m: _names_version(m, "sonnet-5"), "claude-sonnet-5"),
    (lambda m: "opus" in m and "1m" in m, "claude-opus-4-7-1m"),
    (lambda m: "sonnet" in m and "1m" in m, "claude-sonnet-4-8-1m"),
    (lambda m: "mythos-5-1" in m, "claude-mythos-5-1"),
    (lambda m: "fable-5-1" in m, "claude-fable-5-1"),
    (lambda m: "mythos" in m, "claude-mythos-5"),
    (lambda m: "fable" in m, "claude-fable-5"),
    (lambda m: "opus" in m, "claude-opus"),
    (lambda m: "sonnet" in m, "claude-sonnet"),
    (lambda m: "haiku" in m, "claude-haiku"),
]


# Family-only keys are fallback targets, not ids to find inside another id —
# otherwise "claude-opus" would shadow the "1m" and version rules below.
_GENERIC_PRICING_KEYS = frozenset({"claude-opus", "claude-sonnet", "claude-haiku"})

# Specific keys, longest first, so a dated key beats its undated prefix.
_EMBEDDABLE_PRICING_KEYS: tuple[str, ...] = tuple(
    sorted((k for k in MODEL_PRICING if k not in _GENERIC_PRICING_KEYS), key=len, reverse=True)
)


def _embedded_pricing_key(lower: str) -> str | None:
    """Return the longest specific key embedded in ``lower`` at a token boundary.

    Matches provider-prefixed and suffixed ids ("us.anthropic.claude-opus-4-1-
    20250805-v1:0", "claude-opus-4-1@20250805"). The key must not be followed by
    a letter or digit, so "claude-opus-4-1" does not match "claude-opus-4-10",
    nor by another minor-version component, so "claude-opus-5" does not match
    "claude-opus-5-6".
    """
    for key in _EMBEDDABLE_PRICING_KEYS:
        start = lower.find(key)
        while start != -1:
            rest = lower[start + len(key):]
            if not rest[:1].isalnum() and not _MINOR_VERSION_RE.match(rest):
                return key
            start = lower.find(key, start + 1)
    return None


def resolve_pricing_key(model: str) -> str:
    """Map a model ID to its MODEL_PRICING key.

    Order: exact key; bare alias ("opus", "Sonnet", "sonnet[1m]"); longest
    specific key embedded in the lowercased id (with a ``[1m]`` suffix read as
    ``-1m`` and dotted versions read as hyphenated); the ordered fallback
    rules; the default.
    """
    if model in MODEL_PRICING:
        return model
    lower = _DOTTED_VERSION_RE.sub("-", model.lower())
    alias = _BARE_ALIASES.get(lower.removesuffix("[1m]"))
    if alias is not None:
        return alias
    embedded = _embedded_pricing_key(lower.replace("[1m]", "-1m"))
    if embedded is not None:
        return embedded
    for predicate, key in _PRICING_FALLBACK_RULES:
        if predicate(lower):
            return key
    return DEFAULT_PRICING_KEY


def get_model_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_million, output_per_million) for a model ID."""
    return MODEL_PRICING[resolve_pricing_key(model)]


def get_cache_read_multiplier(model: str) -> float:
    """Return the fraction of the input rate charged for a model's cache reads."""
    return _CACHE_READ_MULTIPLIERS.get(resolve_pricing_key(model), _DEFAULT_CACHE_READ_MULTIPLIER)


def compute_raw_cost(
    metrics: TokenMetrics,
    model: str,
    pricing_override: dict[str, float] | None = None,
) -> float:
    """Compute the unscaled list-price dollar cost for a Claude API call."""
    if pricing_override is not None:
        in_rate = pricing_override.get("input", 0.0)
        out_rate = pricing_override.get("output", 0.0)
    else:
        in_rate, out_rate = get_model_pricing(model)

    cache_1h = min(max(metrics.cache_creation_1h_tokens, 0), metrics.cache_creation_tokens)
    cache_5m = metrics.cache_creation_tokens - cache_1h
    return (
        metrics.input_tokens * in_rate
        + metrics.output_tokens * out_rate
        + metrics.cache_read_tokens * (in_rate * get_cache_read_multiplier(model))
        + cache_5m * (in_rate * _CACHE_WRITE_MULTIPLIER)
        + cache_1h * (in_rate * _CACHE_WRITE_1H_MULTIPLIER)
    ) / 1_000_000


def compute_cost(
    metrics: TokenMetrics,
    model: str,
    pricing_override: dict[str, float] | None = None,
) -> float:
    """Compute the dollar cost for a Claude API call.

    The result is scaled by ``cost_multiplier`` from the user config.
    """
    return compute_raw_cost(metrics, model, pricing_override) * _cost_multiplier()
