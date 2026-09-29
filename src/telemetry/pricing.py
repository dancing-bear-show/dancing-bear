"""Pricing engine for Claude API cost calculation.

Holds the one model pricing table (``MODEL_PRICING`` and its resolver) used by
every telemetry cost path, plus the shared cost helpers. ``compute_cost`` is
called by the transcript provider; ``compute_raw_cost`` by OTel analytics
``get_all_costs`` and ``get_daily_costs``.

Two OTel formulas still read ``get_model_pricing`` but compute cost themselves:
``get_model_performance`` (``otel/analytics/cost.py``) and
``_process_api_request`` (``otel/analytics/prompts.py``). Both bill cache writes
at 1x and omit cache reads; moving them onto ``compute_raw_cost`` is deferred
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
- Prompt caching writes: 1.25x base input price
- Prompt caching reads: 0.1x base input price, except per ``_CACHE_READ_MULTIPLIERS``
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
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-1-20250805": (15.0, 75.0),
    # Sonnet 5 launch pricing became standard; the planned Sep 2026 rise to (3.0, 15.0) was cancelled
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-8": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
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

# Cache writes (cache_creation tokens) cost this multiple of the input rate.
_CACHE_WRITE_MULTIPLIER = 1.25


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


# Ordered fallback rules for resolve_pricing_key(): evaluated top-to-bottom
# after an exact MODEL_PRICING match fails. Each predicate takes the
# lowercased model id; the first match wins. Order matters — opus-5-5,
# sonnet-5 and the "1m" combos must be checked before the generic
# opus/sonnet substring checks, and fable/mythos before the haiku default.
_PRICING_FALLBACK_RULES: list[tuple[Callable[[str], bool], str]] = [
    (lambda m: "opus-5-5" in m, "claude-opus-5-5"),
    (lambda m: "sonnet-5" in m, "claude-sonnet-5"),
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


def resolve_pricing_key(model: str) -> str:
    """Map a model ID to its MODEL_PRICING key, with fallback matching."""
    if model in MODEL_PRICING:
        return model
    lower = model.lower()
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

    return (
        metrics.input_tokens * in_rate
        + metrics.output_tokens * out_rate
        + metrics.cache_read_tokens * (in_rate * get_cache_read_multiplier(model))
        + metrics.cache_creation_tokens * (in_rate * _CACHE_WRITE_MULTIPLIER)
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
