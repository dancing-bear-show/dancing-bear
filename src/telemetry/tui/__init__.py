"""Interactive TUI dashboard — built on Textual."""

# Re-export non-textual components eagerly
from telemetry.tui._constants import (  # noqa: F401
    _CLASS_COLORS,
    _CLASS_SYMBOLS,
    _WASTE_TAGS,
)
from telemetry.tui._formatters import (  # noqa: F401
    _bar,
    _event_desc,
    _format_cost,
    _format_tokens,
    format_cost,
    format_tokens,
)
from telemetry.tui._summary import (  # noqa: F401
    SummaryConfig,
    _build_tool_stats,
    _latest_model,
    compute_summary,
)
from telemetry.tui._renderers import (  # noqa: F401
    _agent_detail,
    _efficiency_color,
    _event_input_detail,
    _print_agents_panel,
    _print_tool_stats_panel,
    _render_cls_group,
    _render_header_text,
    _render_stats_compact,
    _render_stats_panel,
    _render_timeline_line,
    _render_tips_text,
    _stats_duration_str,
    _stats_session_label,
    _tip_detail,
    _tool_event_detail,
    _tool_stat_detail,
)
# Textual-dependent modules: lazy-import to avoid ModuleNotFoundError
# when textual is not installed. These are only needed when the TUI runs.


def __getattr__(name: str) -> object:
    """Lazy-load Textual-dependent exports on first access."""
    _textual_exports = {
        "APP_CSS", "_DetailModal", "FooterInfo", "HeaderPanel",
        "SessionPickerScreen", "TipsPanel",
    }
    _stats_exports = {
        "_StatsRenderer", "print_summary", "run_stats",
    }
    _app_exports = {
        "TelemetryTranscriptsApp", "run_live",
    }

    if name in _textual_exports:
        from telemetry.tui import _widgets  # noqa: PLC0415
        return getattr(_widgets, name)
    if name in _stats_exports:
        from telemetry.tui import _stats  # noqa: PLC0415
        return getattr(_stats, name)
    if name in _app_exports:
        from telemetry.tui import _app  # noqa: PLC0415
        return getattr(_app, name)
    raise AttributeError(f"module 'telemetry.tui' has no attribute {name!r}")
