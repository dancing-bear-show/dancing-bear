"""Token pricing for Claude models."""

from __future__ import annotations

PRICING = {
    "opus":   {"input": 15.0,  "output": 75.0,  "cache_read": 1.5,  "cache_create": 18.75},
    "sonnet": {"input": 3.0,   "output": 15.0,  "cache_read": 0.3,  "cache_create": 3.75},
    "haiku":  {"input": 0.8,   "output": 4.0,   "cache_read": 0.08, "cache_create": 1.0},
}


def model_tier(model_id: str) -> str:
    """Map a model ID string to a pricing tier."""
    lower = model_id.lower()
    for tier in ("opus", "sonnet", "haiku"):
        if tier in lower:
            return tier
    return "haiku"


def compute_cost(input_tok: int, output_tok: int,
                 cache_read: int, cache_create: int,
                 model: str) -> float:
    """Compute dollar cost from token counts and model ID."""
    r = PRICING[model_tier(model)]
    return (input_tok * r["input"] + output_tok * r["output"] +
            cache_read * r["cache_read"] + cache_create * r["cache_create"]) / 1_000_000
