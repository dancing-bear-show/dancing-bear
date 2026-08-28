"""Display formatting helpers for the menubar app."""

from datetime import datetime, timedelta, timezone

from core.date_utils import now_utc

_BLOCK_CHARS = " ▁▂▃▄▅▆▇█"  # index 0 = space (zero)
_BLOCK_LEVELS = len(_BLOCK_CHARS) - 1  # 8 non-zero levels


def _sparkline(hourly_costs: list[float]) -> str:
    if not hourly_costs or all(c <= 0.0 for c in hourly_costs):
        return "  (no activity)"
    peak = max(hourly_costs)
    chars: list[str] = []
    for cost in hourly_costs:
        if cost <= 0.0:
            chars.append(_BLOCK_CHARS[0])
        else:
            level = max(1, round(cost / peak * _BLOCK_LEVELS))
            chars.append(_BLOCK_CHARS[level])
    return "  " + "".join(chars)


def _rate_str(cost: float, window_secs: int, avg_hourly: float) -> str:
    hours = max(window_secs, 1) / 3600.0
    current_rate = cost / hours
    flag = "!" if avg_hourly > 0 and current_rate > 2 * avg_hourly else ""
    return f"  Rate: ${current_rate:.2f}/hr  (avg ${avg_hourly:.2f}/hr){flag}"


def _model_short(name: str) -> str:
    return name.removeprefix("claude-")[:18]


def _window_since_impl(seconds: int | None) -> datetime:
    """Internal implementation of _window_since; imported by _menubar_app."""
    if seconds is None:
        local_midnight = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return local_midnight.astimezone(timezone.utc)
    return now_utc() - timedelta(seconds=seconds)


def _age_str(age_secs: float) -> str:
    if age_secs < 3600:
        return f"{int(age_secs // 60)}m ago"
    return f"{age_secs / 3600:.1f}h ago"
