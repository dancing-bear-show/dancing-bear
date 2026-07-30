"""Formatting helpers for costs, token counts, progress bars, and event descriptions."""

from telemetry.models import SessionEvent


def format_cost(cost: float, estimated: bool = False) -> str:
    prefix = "~" if estimated else ""
    return f"{prefix}${cost:.2f}"


# Aliases kept for any existing callers within this module
_format_cost = format_cost


def format_tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count // 1_000}K"
    return str(count)


_format_tokens = format_tokens


def _bar(fraction: float, width: int = 10) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _event_desc(evt: SessionEvent) -> str:
    """Extract a short description from a tool event's input."""
    inp = evt.tool_input or {}
    desc = (
        inp.get("file_path", "")
        or inp.get("command", "")
        or inp.get("pattern", "")
        or inp.get("skill", "")
        or inp.get("description", "")
        or ""
    )
    if "/" in desc:
        desc = desc.split("/")[-1]
    return desc[:30]
