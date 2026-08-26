"""Formatting helpers for costs, token counts, progress bars, and event descriptions."""

from core.format_utils import format_tokens
from telemetry.models import SessionEvent

# Alias used by callers that import from this module
_format_tokens = format_tokens


def format_cost(cost: float, estimated: bool = False) -> str:
    prefix = "~" if estimated else ""
    return f"{prefix}${cost:.2f}"


# Aliases kept for any existing callers within this module
_format_cost = format_cost


def _bar(fraction: float, width: int = 10) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


# Tool-input keys worth showing, most specific first; the first non-empty wins.
_DESC_KEYS = ("file_path", "command", "pattern", "skill", "description")


def _event_desc(evt: SessionEvent) -> str:
    """Extract a short description from a tool event's input."""
    inp = evt.tool_input or {}
    desc = next((v for k in _DESC_KEYS if (v := inp.get(k))), "")
    if "/" in desc:
        desc = desc.split("/")[-1]
    return desc[:30]
