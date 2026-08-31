"""TelemetryMenubarApp and supporting helpers for the macOS menubar app."""

import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import rumps
    _HAS_RUMPS = True
    _AppBase = rumps.App
except ImportError:
    _HAS_RUMPS = False
    rumps = None
    _AppBase = object

from telemetry.otel.menubar_provider import OtelDisplayData, OtelMenubarProvider
from telemetry.ccpulse_reader import read_current as _read_ccpulse
from telemetry.models import SessionSummary
from telemetry.providers.transcript import TranscriptProvider
from core.format_utils import format_tokens as _format_tokens
from telemetry.tui import format_cost as _format_cost
from telemetry._menubar_budget import _budget_score
from telemetry._menubar_config import (
    _DEFAULT_ICON_TEMPLATE,
    _DEFAULT_MONTHLY_BUDGET,
    _DEFAULT_POLL_INTERVAL,
    _INSIGHTS_TIP_ROWS,
    _OTEL_SECTION_KEYS,
    _any_otel_sections_enabled,
    _icon_template_vars,
    _load_config,
)
from core.date_utils import now_utc
from telemetry._menubar_display import (
    _age_str,
    _model_short,
    _rate_str,
    _sparkline,
    _window_since_impl,
)
from telemetry._menubar_renderers import _render_icon_plain
from telemetry._menubar_app_otel import OtelSectionsMixin
from telemetry._menubar_app_insights import InsightsMixin
from telemetry._menubar_app_actions import ActionsMixin

_CLAUDE_DIR = Path.home() / ".claude"
_PROJECTS_DIR = _CLAUDE_DIR / "projects"

_STORAGE_WARN_DAYS = 30
_VERSION = "v1.1.0"

# Cycle order: (label, seconds) — None seconds means "since today midnight"
_WINDOWS: list[tuple[str, int | None]] = [
    ("last 1h", 3600),
    ("today", None),
    ("last 7d", 7 * 86400),
    ("last 30d", 30 * 86400),
]

# Cycle order for OTel time windows: (label, window_str) passed to get_display_data()
_OTEL_WINDOWS: list[tuple[str, str]] = [
    ("last 1h", "1h"),
    ("last 24h", "24h"),
    ("last 7d", "7d"),
    ("last 30d", "30d"),
]

_app_version_cache: str | None = None


@dataclass(frozen=True)
class MenuRefreshData:
    """Current-window usage metrics passed to _update_menu."""

    window_totals: dict
    avg_hourly: float
    mtd_cost: float


def _build_version() -> str:
    try:
        sha = subprocess.check_output(  # nosec B603 B607 - fixed git command with no user input
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return f"{_VERSION} ({sha})"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return _VERSION


def _get_app_version() -> str:
    global _app_version_cache  # noqa: PLW0603
    if _app_version_cache is None:
        _app_version_cache = _build_version()
    return _app_version_cache


def _month_since() -> datetime:
    """Return UTC midnight on the 1st of the current calendar month."""
    now = now_utc()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _window_since(seconds: int | None) -> datetime:
    """Return the UTC datetime marking the start of the window."""
    return _window_since_impl(seconds)


def _project_short(s: SessionSummary) -> str:
    if not s.project_path:
        return s.session_id[:8]
    parts = [p for p in s.project_path.split("/") if p]
    return parts[-1][:28] if parts else s.session_id[:8]


class TelemetryMenubarApp(OtelSectionsMixin, InsightsMixin, ActionsMixin, _AppBase):  # pragma: no cover

    _DETAIL_SESSIONS = 2

    def __init__(self) -> None:
        if not _HAS_RUMPS:
            raise RuntimeError("ClaudeStats requires rumps — macOS only. Install with: pip install rumps")
        import telemetry.menubar as _menubar_shim
        _menubar_shim._acquire_instance_lock()
        super().__init__(name="ClaudeStats", title="...", icon=None, quit_button=None)

        self._transcript = TranscriptProvider()
        self._otel = OtelMenubarProvider()
        self._window_idx = 0
        self._otel_window_idx: int = 0
        self._otel_data_available: bool = False
        self._otel_cost_1d: float = 0.0
        self._last_cfg: dict = {}
        self._poll_timer: "rumps.Timer | None" = None
        self._refresh_running: bool = False
        self._refresh_count: int = 0
        self._cached_avg_hourly: float = 0.0
        self._cached_mtd_cost: float = 0.0

        self._hdr_usage = rumps.MenuItem("-- Usage --", callback=self._on_cycle_window)
        self._info_usage_cost = rumps.MenuItem("  Cost: ...")
        self._info_usage_cost.set_callback(None)
        self._info_usage_tokens = rumps.MenuItem("  Tokens: ...")
        self._info_usage_tokens.set_callback(None)
        self._info_usage_sessions = rumps.MenuItem("  Sessions: ...")
        self._info_usage_sessions.set_callback(None)
        self._info_usage_rate = rumps.MenuItem("  Rate: ...")
        self._info_usage_rate.set_callback(None)
        self._info_usage_sparkline = rumps.MenuItem("  ...")
        self._info_usage_sparkline.set_callback(None)

        self._hdr_models = rumps.MenuItem("-- Models --")
        self._hdr_models.set_callback(None)
        self._model_rows: list[rumps.MenuItem] = []
        for _ in range(4):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._model_rows.append(item)

        self._hdr_sessions = rumps.MenuItem("-- Active Sessions (last 1h) --")
        self._hdr_sessions.set_callback(None)
        self._session_rows: list[rumps.MenuItem] = []
        for _ in range(self._DETAIL_SESSIONS):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._session_rows.append(item)
        self._session_more = rumps.MenuItem("  -")
        self._session_more.set_callback(None)

        self._hdr_insights = rumps.MenuItem("-- Insights --")
        self._hdr_insights.set_callback(None)
        self._info_insights_summary = rumps.MenuItem("  -")
        self._info_insights_summary.set_callback(None)
        self._insights_tip_rows: list[rumps.MenuItem] = []
        self._insights_tip_hints: list[dict] = [{} for _ in range(_INSIGHTS_TIP_ROWS)]
        for i in range(_INSIGHTS_TIP_ROWS):
            item = rumps.MenuItem(
                f"  insights_tip_{i + 1}",
                callback=self._make_tip_click_handler(i),
            )
            self._insights_tip_rows.append(item)

        self._hdr_otel_usage = rumps.MenuItem("", callback=self._on_cycle_otel_window)
        self._otel_usage_rows: list[rumps.MenuItem] = []
        for _ in range(4):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._otel_usage_rows.append(item)

        self._hdr_otel_models = rumps.MenuItem("")
        self._hdr_otel_models.set_callback(None)
        self._otel_model_rows: list[rumps.MenuItem] = []
        for _ in range(4):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._otel_model_rows.append(item)

        self._hdr_otel_meta = rumps.MenuItem("")
        self._hdr_otel_meta.set_callback(None)
        self._otel_meta_rows: list[rumps.MenuItem] = []
        for _ in range(4):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._otel_meta_rows.append(item)

        self._hdr_hooks = rumps.MenuItem("")
        self._hdr_hooks.set_callback(None)
        self._hook_rows: list[rumps.MenuItem] = []
        for _ in range(4):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._hook_rows.append(item)

        self._hdr_tools = rumps.MenuItem("")
        self._hdr_tools.set_callback(None)
        self._tool_rows: list[rumps.MenuItem] = []
        for _ in range(5):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._tool_rows.append(item)

        self._hdr_code = rumps.MenuItem("")
        self._hdr_code.set_callback(None)
        self._code_rows: list[rumps.MenuItem] = []
        for _ in range(5):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._code_rows.append(item)

        self._hdr_skills = rumps.MenuItem("")
        self._hdr_skills.set_callback(None)
        self._skill_rows: list[rumps.MenuItem] = []
        for _ in range(2):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._skill_rows.append(item)

        self._hdr_session_patterns = rumps.MenuItem("")
        self._hdr_session_patterns.set_callback(None)
        self._session_pattern_rows: list[rumps.MenuItem] = []
        for _ in range(3):
            item = rumps.MenuItem("  -")
            item.set_callback(None)
            self._session_pattern_rows.append(item)

        self._info_refresh_stat = rumps.MenuItem("  Refresh: —")
        self._info_refresh_stat.set_callback(None)
        self._info_version = rumps.MenuItem(f"  {_get_app_version()}")
        self._info_version.set_callback(None)
        self._btn_configure = rumps.MenuItem("  Configure…", callback=self._on_configure)
        self._btn_clear = rumps.MenuItem("  Clear sessions older than 30d...", callback=self._on_clear)
        self._btn_login_item = rumps.MenuItem("  Start at login", callback=self._on_toggle_login_item)
        self._btn_quit = rumps.MenuItem("Quit", callback=rumps.quit_application)

        initial_cfg = _load_config()
        self._rebuild_menu(initial_cfg)

        poll_secs = int(initial_cfg.get("poll_interval", _DEFAULT_POLL_INTERVAL))
        self._poll_timer = rumps.Timer(self._refresh, poll_secs)
        self._poll_timer.start()
        rumps.Timer(self._refresh_once, 0.5).start()

    def _otel_section_specs(self) -> list[tuple[str, object, list]]:
        """Return (config_key, header_item, row_items) for each OTel menu section."""
        return [
            ("otel_usage", self._hdr_otel_usage, self._otel_usage_rows),
            ("otel_models", self._hdr_otel_models, self._otel_model_rows),
            ("otel_meta", self._hdr_otel_meta, self._otel_meta_rows),
            ("otel_hooks", self._hdr_hooks, self._hook_rows),
            ("otel_tools", self._hdr_tools, self._tool_rows),
            ("otel_code", self._hdr_code, self._code_rows),
            ("otel_skills", self._hdr_skills, self._skill_rows),
            ("otel_sessions", self._hdr_session_patterns, self._session_pattern_rows),
        ]

    def _append_otel_items(self, items: list, s: dict) -> None:
        """Append enabled OTel section headers/rows to items, with a separator if needed."""
        if not self._otel_data_available:
            return
        for key, hdr, rows in self._otel_section_specs():
            if s.get(key, {}).get("enabled", False):
                prefix = [None] if items else []
                items += [*prefix, hdr, *rows]

    def _append_usage_items(self, items: list, u: dict) -> None:
        """Append the usage section (cost + optional detail rows) to items."""
        if not u["enabled"]:
            return
        prefix = [None] if items else []
        items += [*prefix, self._hdr_usage, self._info_usage_cost]
        optional_rows = [
            (u["show_tokens"], self._info_usage_tokens),
            (u["show_sessions"], self._info_usage_sessions),
            (u["show_rate"], self._info_usage_rate),
            (u["show_sparkline"], self._info_usage_sparkline),
        ]
        items += [row for enabled, row in optional_rows if enabled]

    def _rebuild_menu(self, cfg: dict) -> None:  # NOSONAR - menu section assembly; sequential structure is inherent
        s = cfg["sections"]
        items: list = []
        self._append_otel_items(items, s)
        self._append_usage_items(items, s["usage"])
        if s["models"]["enabled"]:
            items += [None, self._hdr_models, *self._model_rows]
        if s["active_sessions"]["enabled"]:
            items += [None, self._hdr_sessions, *self._session_rows, self._session_more]
        if s["insights"]["enabled"]:
            items += [None, self._hdr_insights, self._info_insights_summary, *self._insights_tip_rows]
        items += [
            None, self._info_refresh_stat, self._info_version,
            self._btn_configure, self._btn_clear, self._btn_login_item,
            None, self._btn_quit,
        ]
        self.menu.clear()
        self.menu = items
        from telemetry import login_item as _li
        self._btn_login_item.state = 1 if _li.is_enabled() else 0

    def _on_cycle_window(self, _sender: object) -> None:  # noqa: ARG002
        self._window_idx = (self._window_idx + 1) % len(_WINDOWS)
        self._refresh(None)

    def _on_cycle_otel_window(self, _sender: object) -> None:  # noqa: ARG002
        self._otel_window_idx = (self._otel_window_idx + 1) % len(_OTEL_WINDOWS)
        self._refresh(None)

    def _refresh_once(self, sender: object) -> None:
        sender.stop()
        self._refresh(sender)

    def _restart_poll_timer_if_changed(self, cfg: dict) -> None:
        """Restart the poll timer if cfg's poll_interval differs from the last-seen config."""
        new_interval = int(cfg.get("poll_interval", _DEFAULT_POLL_INTERVAL))
        old_interval = int(self._last_cfg.get("poll_interval", _DEFAULT_POLL_INTERVAL))
        if new_interval == old_interval or self._poll_timer is None:
            return
        self._poll_timer.stop()
        self._poll_timer = rumps.Timer(self._refresh, new_interval)
        self._poll_timer.start()

    def _refresh(self, _sender: object) -> None:  # noqa: ARG002
        if self._refresh_running:
            return
        self._refresh_running = True
        t0 = time.monotonic()
        try:
            cfg = _load_config()
            cfg_changed = cfg != self._last_cfg
            if cfg_changed:
                self._restart_poll_timer_if_changed(cfg)
                self._last_cfg = cfg
            s = cfg["sections"]
            window_totals = self._load_window_totals()
            self._refresh_count += 1
            if self._refresh_count == 1 or self._refresh_count % 10 == 0:
                self._cached_avg_hourly = self._load_avg_hourly()
                self._cached_mtd_cost = self._load_mtd_cost()
            avg_hourly = self._cached_avg_hourly
            mtd_cost = self._cached_mtd_cost
            recent = self._load_recent() if s["active_sessions"]["enabled"] else []
            insights = self._load_insights() if s["insights"]["enabled"] else None
            icon_template = str(cfg.get("icon_display") or _DEFAULT_ICON_TEMPLATE)
            icon_ctx = self._fetch_icon_window_totals(icon_template, window_totals, cfg)
            prev_otel_available = self._otel_data_available
            self._update_menu(
                MenuRefreshData(window_totals, avg_hourly, mtd_cost),
                recent, cfg, insights, icon_window_totals=icon_ctx,
            )
            if cfg_changed or self._otel_data_available != prev_otel_available:
                self._rebuild_menu(cfg)
            elapsed = time.monotonic() - t0
            self._info_refresh_stat.title = f"  Refresh: {elapsed:.1f}s"
        except Exception:  # nosec B110 - menubar refresh errors are non-fatal; app continues running
            self.title = "?"
        finally:
            self._refresh_running = False

    def _refresh_otel_icon_cost(self) -> None:
        try:
            od = self._otel.get_display_data(window="24h")
            if od.available and od.otel_usage is not None:
                self._otel_cost_1d = od.otel_usage.cost_24h
            else:
                self._otel_cost_1d = 0.0
        except Exception:  # nosec B110 - OTel unavailability is expected; icon falls back to 0.0
            self._otel_cost_1d = 0.0

    def _fetch_icon_window_totals(self, template: str, window_totals: dict, cfg: dict | None = None) -> dict[str, dict]:
        refs = _icon_template_vars(template)
        out: dict[str, dict] = {}
        _, current_secs = _WINDOWS[self._window_idx]
        if "1h_spend" in refs or "tokens_1h" in refs:
            out["1h"] = window_totals if current_secs == 3600 else self._load_window_totals_for(3600)
        if "1d_spend" in refs:
            out["1d"] = window_totals if current_secs is None else self._load_window_totals_for(None)
        if "otel_1d" in refs and not _any_otel_sections_enabled(cfg or {}):
            self._refresh_otel_icon_cost()
        return out

    def _load_insights(self) -> dict | None:
        try:
            return _read_ccpulse()
        except Exception:  # nosec B110 - ccpulse unavailability is expected; insights section shows placeholder
            return None

    def _load_window_totals(self) -> dict:
        try:
            _, secs = _WINDOWS[self._window_idx]
            return self._transcript.get_windowed_totals(since=_window_since(secs))
        except Exception:  # nosec B110 - transcript read failures are non-fatal; show zeroes
            return {
                "cost": 0.0, "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "sessions": 0,
                "cost_is_estimated": False, "models": {}, "hourly_costs": [0.0] * 12,
            }

    def _load_avg_hourly(self) -> float:
        try:
            totals = self._transcript.get_windowed_totals(since=_window_since(30 * 86400))
            return totals["cost"] / (30 * 24)
        except Exception:  # nosec B110 - transcript read failure falls back to 0.0
            return 0.0

    def _load_mtd_cost(self) -> float:
        try:
            totals = self._transcript.get_windowed_totals(since=_month_since())
            return float(totals["cost"])
        except Exception:  # nosec B110 - transcript read failure falls back to 0.0
            return 0.0

    def _load_recent(self) -> list[SessionSummary]:
        try:
            _, secs = _WINDOWS[self._window_idx]
            since = _window_since(secs)
            return self._transcript.get_sessions(since=since)
        except Exception:  # nosec B110 - transcript read failure returns empty list
            return []

    def _set_icon(self, template: str, icon_ctx: dict[str, dict], mtd_cost: float, budget: float) -> None:
        score = _budget_score(mtd_cost, budget)
        otel_cost_1d = self._otel_cost_1d
        # Late import from menubar shim so tests can patch menubar._HAS_APPKIT and
        # menubar.NSColor / NSFont etc. via patch.multiple(menubar_module, ...).
        import telemetry.menubar as _mb
        if _mb._HAS_APPKIT:
            try:
                attr = _mb._compose_icon_attributed(template, icon_ctx, mtd_cost, score, otel_cost_1d)
                self._nsapp.nsstatusitem.setAttributedTitle_(attr)
                return
            except Exception:  # nosec B110 - AppKit error falls back to plain text icon
                pass
        self.title = _render_icon_plain(template, icon_ctx, mtd_cost, score, otel_cost_1d)

    def _load_window_totals_for(self, secs: int | None) -> dict:
        try:
            return self._transcript.get_windowed_totals(since=_window_since(secs))
        except Exception:  # nosec B110 - transcript read failure returns empty dict
            return {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}

    def _update_menu(
        self, data: MenuRefreshData, recent: list[SessionSummary],
        cfg: dict, insights: dict | None = None,
        icon_window_totals: dict | None = None,
    ) -> None:
        budget = float(cfg.get("monthly_budget") or _DEFAULT_MONTHLY_BUDGET)
        icon_template = str(cfg.get("icon_display") or _DEFAULT_ICON_TEMPLATE)
        label, secs = _WINDOWS[self._window_idx]
        next_label, _ = _WINDOWS[(self._window_idx + 1) % len(_WINDOWS)]
        self._hdr_usage.title = f"-- Usage ({label}) [click: {next_label}] --"
        window_totals = data.window_totals
        total_cost = window_totals["cost"]
        total_in = window_totals["input_tokens"]
        total_out = window_totals["output_tokens"]
        any_estimated = window_totals["cost_is_estimated"]
        window_secs = secs if secs is not None else int(
            (now_utc() - _window_since(None)).total_seconds()
        )
        self._info_usage_cost.title = f"  Cost: {_format_cost(total_cost, any_estimated)}"
        self._info_usage_tokens.title = (
            f"  Tokens: {_format_tokens(total_in)} in / {_format_tokens(total_out)} out"
        )
        self._info_usage_sessions.title = f"  Sessions: {window_totals['sessions']}"
        self._info_usage_rate.title = _rate_str(total_cost, window_secs, data.avg_hourly)
        self._info_usage_sparkline.title = _sparkline(window_totals.get("hourly_costs", []))
        self._set_icon(icon_template, icon_window_totals or {}, data.mtd_cost, budget)
        self._update_conditional_sections(window_totals, recent, cfg, insights, label)

    def _apply_otel_data(self, otel_data: OtelDisplayData | None, s: dict) -> None:
        """Update OTel sections and cached 1d cost from a fetched OtelDisplayData (or None)."""
        if otel_data is None:
            self._otel_data_available = False
            return
        self._update_otel_sections(otel_data, s)
        self._otel_data_available = otel_data.available
        if otel_data.available and otel_data.otel_usage is not None:
            self._otel_cost_1d = otel_data.otel_usage.cost_24h
        else:
            self._otel_cost_1d = 0.0

    def _update_conditional_sections(
        self, window_totals: dict, recent: list[SessionSummary],
        cfg: dict, insights: dict | None, label: str,
    ) -> None:
        s = cfg["sections"]
        if s["models"]["enabled"]:
            self._hdr_models.title = f"-- Models ({label}) --"
            self._update_model_rows(window_totals.get("models", {}))
        if s["active_sessions"]["enabled"]:
            self._update_session_rows(recent, label)
        if s["insights"]["enabled"]:
            self._render_insights(insights, max_tips=s["insights"]["max_tips"])

        _any_otel_enabled = any(s.get(k, {}).get("enabled", False) for k in _OTEL_SECTION_KEYS)
        _, otel_window = _OTEL_WINDOWS[self._otel_window_idx]
        otel_data = self._otel.get_display_data(window=otel_window) if _any_otel_enabled else None

        self._apply_otel_data(otel_data, s)

    def _update_model_rows(self, models: dict[str, float]) -> None:
        ranked = sorted(models.items(), key=lambda kv: kv[1], reverse=True)
        for idx, row in enumerate(self._model_rows):
            if idx < len(ranked):
                name, cost = ranked[idx]
                row.title = f"  {_model_short(name):<18}  {_format_cost(cost)}"
            else:
                row.title = "  -" if ranked else "  (none)"

    @staticmethod
    def _format_session_row_title(s: SessionSummary, now_ts: float) -> str:
        """Build the menu row title for one active-session summary."""
        age_ref = s.end_time or s.start_time
        age_secs = now_ts - age_ref.timestamp()
        return (
            f"  {_project_short(s)}"
            f"  {_format_cost(s.total_cost, s.cost_is_estimated)}"
            f"  {_format_tokens(s.input_tokens)}in/{_format_tokens(s.output_tokens)}out"
            f"  {_age_str(age_secs)}"
        )

    def _session_more_title(self, recent: list[SessionSummary], label: str) -> str:
        """Build the '...and N more' summary title, or a fallback when empty."""
        rest = recent[self._DETAIL_SESSIONS:]
        if rest:
            return f"  ...and {len(rest)} more  {_format_cost(sum(s.total_cost for s in rest))}"
        if recent:
            return "  -"
        return f"  no sessions in {label}"

    def _update_session_rows(self, recent: list[SessionSummary], label: str) -> None:
        self._hdr_sessions.title = f"-- Active Sessions ({label}) --"
        now_ts = time.time()
        for idx, row in enumerate(self._session_rows):
            row.title = (
                self._format_session_row_title(recent[idx], now_ts) if idx < len(recent) else "  -"
            )
        self._session_more.title = self._session_more_title(recent, label)
