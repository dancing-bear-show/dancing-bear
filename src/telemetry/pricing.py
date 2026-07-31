"""Pricing engine for Claude API cost calculation.

Locally-computed costs use Anthropic's public list prices as of Apr 2026.
``cost_multiplier`` in ``~/.claude/claudestats.json`` scales the result for
calibration against actual billed spend. Default is 1.0 (no scaling).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_CONFIG_PATH = Path.home() / ".claude" / "claudestats.json"

# (mtime, multiplier) cache so we don't re-read the JSON on every call.
_mult_cache: tuple[float, float] = (-1.0, 1.0)

# Model pricing (input_per_million, output_per_million) — Apr 2026
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-8": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-7-1m": (5.0, 25.0),
    "claude-opus-4-6-1m": (5.0, 25.0),
    "claude-sonnet-4-8-1m": (3.0, 15.0),
    "claude-sonnet-4-6-1m": (3.0, 15.0),
    "claude-opus": (5.0, 25.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
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

    Returns "opus", "sonnet", "haiku", or "unknown".
    """
    lower = model_id.lower()
    for tier in ("opus", "sonnet", "haiku"):
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


def _get_model_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_million, output_per_million) for a model ID."""
    if model in _MODEL_PRICING:
        return _MODEL_PRICING[model]
    lower = model.lower()
    if "opus" in lower and "1m" in lower:
        return _MODEL_PRICING["claude-opus-4-7-1m"]
    if "sonnet" in lower and "1m" in lower:
        return _MODEL_PRICING["claude-sonnet-4-8-1m"]
    if "opus" in lower:
        return _MODEL_PRICING["claude-opus"]
    if "sonnet" in lower:
        return _MODEL_PRICING["claude-sonnet"]
    if "haiku" in lower:
        return _MODEL_PRICING["claude-haiku"]
    return _MODEL_PRICING["claude-haiku"]  # default


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
        + metrics.cache_read_tokens * (in_rate / 10)
        + metrics.cache_creation_tokens * (in_rate * 1.25)
    ) / 1_000_000
    return raw * _cost_multiplier()
