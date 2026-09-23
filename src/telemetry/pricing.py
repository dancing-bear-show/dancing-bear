"""Pricing engine for Claude API cost calculation.

Locally-computed costs use Anthropic's public list prices as of Apr 2026.
``cost_multiplier`` in ``~/.claude/claudestats.json`` scales the result for
calibration against actual billed spend. Default is 1.0 (no scaling).
"""

from __future__ import annotations

from collections.abc import Callable

import json
import re
from dataclasses import dataclass

from telemetry.constants import CONFIG_PATH as _CONFIG_PATH

# (mtime, multiplier) cache so we don't re-read the JSON on every call.
_mult_cache: tuple[float, float] = (-1.0, 1.0)

# Model pricing (input_per_million, output_per_million) — Apr 2026
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-8": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
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

# Cache reads cost this fraction of the input rate. Most models use 0.1x;
# keys are _MODEL_PRICING keys, so fallback-matched variants inherit them.
_DEFAULT_CACHE_READ_MULTIPLIER = 0.1
_CACHE_READ_MULTIPLIERS: dict[str, float] = {
    "claude-opus-5-5": 0.05,
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
}


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


# Ordered fallback rules for _get_model_pricing(): evaluated top-to-bottom
# after an exact _MODEL_PRICING match fails. Each predicate takes the
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


def _resolve_pricing_key(model: str) -> str:
    """Map a model ID to its _MODEL_PRICING key, with fallback matching."""
    if model in _MODEL_PRICING:
        return model
    lower = model.lower()
    for predicate, key in _PRICING_FALLBACK_RULES:
        if predicate(lower):
            return key
    return "claude-haiku"  # default


def _get_model_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_million, output_per_million) for a model ID."""
    return _MODEL_PRICING[_resolve_pricing_key(model)]


def _cache_read_multiplier(model: str) -> float:
    """Return the fraction of the input rate charged for a model's cache reads."""
    return _CACHE_READ_MULTIPLIERS.get(_resolve_pricing_key(model), _DEFAULT_CACHE_READ_MULTIPLIER)


def compute_cost(
    metrics: TokenMetrics,
    model: str,
    pricing_override: dict[str, float] | None = None,
) -> float:
    """Compute the dollar cost for a Claude API call.

    The result is scaled by ``cost_multiplier`` from the user config.
    """
    if pricing_override is not None:
        in_rate = pricing_override.get("input", 0.0)
        out_rate = pricing_override.get("output", 0.0)
    else:
        in_rate, out_rate = _get_model_pricing(model)

    raw = (
        metrics.input_tokens * in_rate
        + metrics.output_tokens * out_rate
        + metrics.cache_read_tokens * (in_rate * _cache_read_multiplier(model))
        + metrics.cache_creation_tokens * (in_rate * 1.25)
    ) / 1_000_000
    return raw * _cost_multiplier()
