"""TelemetryMenubarApp and supporting helpers for the macOS menubar app."""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import rumps
    _HAS_RUMPS = True
    _AppBase = rumps.App
except ImportError:
    _HAS_RUMPS = False
    rumps = None  # type: ignore[assignment]
    _AppBase = object  # type: ignore[assignment,misc]

try:
    # Only NSPasteboard/NSPasteboardTypeString are used here; the attributed-string
    # helpers (_compose_icon_attributed, _score_color) live in menubar.py so that
    # tests can patch their AppKit dependencies via that module's namespace.
    from AppKit import (  # type: ignore[import-not-found]
        NSPasteboard,
        NSPasteboardTypeString,
    )
    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False

from telemetry.otel.menubar_provider import OtelDisplayData, OtelMenubarProvider
from telemetry import login_item as _login_item
from telemetry.ccpulse_reader import read_current as _read_ccpulse
from telemetry.models import SessionSummary
from telemetry.providers.transcript import TranscriptProvider
from telemetry.tui import (
    format_cost as _format_cost,
    format_tokens as _format_tokens,
)
from telemetry._menubar_config import (
    _DEFAULT_ICON_TEMPLATE,
    _DEFAULT_MONTHLY_BUDGET,
    _DEFAULT_POLL_INTERVAL,
    _INSIGHTS_TIP_ROWS,
    _MAX_TIPS_LIMIT,
    _OTEL_SECTION_KEYS,
    _any_otel_sections_enabled,
    _config_to_text,
    _icon_template_vars,
    _load_config,
    _parse_config_text,
    _save_config,
)
from telemetry._menubar_display import (
    _age_str,
    _model_short,
    _rate_str,
    _sparkline,
    _window_since_impl,
)

# Re-export helpers that were split into sibling modules.
# Downstream importers (menubar.py) continue to pull these from _menubar_app.
from telemetry._menubar_budget import (  # noqa: F401
    _budget_score,
    _safe_float,
    _safe_int,
)
from telemetry._menubar_renderers import (  # noqa: F401
    _icon_substitutions,
    _icon_token_stream,
    _render_icon_plain,
)

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
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _window_since(seconds: int | None) -> datetime:
    """Return the UTC datetime marking the start of the window."""
    return _window_since_impl(seconds)


def _project_short(s: SessionSummary) -> str:
    if not s.project_path:
        return s.session_id[:8]
    parts = [p for p in s.project_path.split("/") if p]
    return parts[-1][:28] if parts else s.session_id[:8]


class TelemetryMenubarApp(_AppBase):  # pragma: no cover

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

    def _rebuild_menu(self, cfg: dict) -> None:  # NOSONAR - menu section assembly; sequential structure is inherent
        s = cfg["sections"]
        u = s["usage"]
        items: list = []
        if self._otel_data_available:
            _otel_sections = [
                ("otel_usage", self._hdr_otel_usage, self._otel_usage_rows),
                ("otel_models", self._hdr_otel_models, self._otel_model_rows),
                ("otel_meta", self._hdr_otel_meta, self._otel_meta_rows),
                ("otel_hooks", self._hdr_hooks, self._hook_rows),
                ("otel_tools", self._hdr_tools, self._tool_rows),
                ("otel_code", self._hdr_code, self._code_rows),
                ("otel_skills", self._hdr_skills, self._skill_rows),
                ("otel_sessions", self._hdr_session_patterns, self._session_pattern_rows),
            ]
            for key, hdr, rows in _otel_sections:
                if s.get(key, {}).get("enabled", False):
                    prefix = [None] if items else []
                    items += [*prefix, hdr, *rows]
        if u["enabled"]:
            prefix = [None] if items else []
            items += [*prefix, self._hdr_usage, self._info_usage_cost]
            if u["show_tokens"]:
                items.append(self._info_usage_tokens)
            if u["show_sessions"]:
                items.append(self._info_usage_sessions)
            if u["show_rate"]:
                items.append(self._info_usage_rate)
            if u["show_sparkline"]:
                items.append(self._info_usage_sparkline)
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
        self._btn_login_item.state = 1 if _login_item.is_enabled() else 0

    def _on_cycle_window(self, _sender: object) -> None:  # noqa: ARG002
        self._window_idx = (self._window_idx + 1) % len(_WINDOWS)
        self._refresh(None)

    def _on_cycle_otel_window(self, _sender: object) -> None:  # noqa: ARG002
        self._otel_window_idx = (self._otel_window_idx + 1) % len(_OTEL_WINDOWS)
        self._refresh(None)

    def _refresh_once(self, sender: object) -> None:
        sender.stop()
        self._refresh(sender)

    def _refresh(self, _sender: object) -> None:  # noqa: ARG002
        if self._refresh_running:
            return
        self._refresh_running = True
        t0 = time.monotonic()
        try:
            cfg = _load_config()
            cfg_changed = cfg != self._last_cfg
            if cfg_changed:
                new_interval = int(cfg.get("poll_interval", _DEFAULT_POLL_INTERVAL))
                old_interval = int(self._last_cfg.get("poll_interval", _DEFAULT_POLL_INTERVAL))
                if new_interval != old_interval and self._poll_timer is not None:
                    self._poll_timer.stop()
                    self._poll_timer = rumps.Timer(self._refresh, new_interval)
                    self._poll_timer.start()
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
            self._update_menu(window_totals, avg_hourly, mtd_cost, recent, cfg, insights, icon_window_totals=icon_ctx)
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
        self, window_totals: dict, avg_hourly: float, mtd_cost: float,
        recent: list[SessionSummary], cfg: dict, insights: dict | None = None,
        icon_window_totals: dict | None = None,
    ) -> None:
        budget = float(cfg.get("monthly_budget") or _DEFAULT_MONTHLY_BUDGET)
        icon_template = str(cfg.get("icon_display") or _DEFAULT_ICON_TEMPLATE)
        label, secs = _WINDOWS[self._window_idx]
        next_label, _ = _WINDOWS[(self._window_idx + 1) % len(_WINDOWS)]
        self._hdr_usage.title = f"-- Usage ({label}) [click: {next_label}] --"
        total_cost = window_totals["cost"]
        total_in = window_totals["input_tokens"]
        total_out = window_totals["output_tokens"]
        any_estimated = window_totals["cost_is_estimated"]
        window_secs = secs if secs is not None else int(
            (datetime.now(timezone.utc) - _window_since(None)).total_seconds()
        )
        self._info_usage_cost.title = f"  Cost: {_format_cost(total_cost, any_estimated)}"
        self._info_usage_tokens.title = (
            f"  Tokens: {_format_tokens(total_in)} in / {_format_tokens(total_out)} out"
        )
        self._info_usage_sessions.title = f"  Sessions: {window_totals['sessions']}"
        self._info_usage_rate.title = _rate_str(total_cost, window_secs, avg_hourly)
        self._info_usage_sparkline.title = _sparkline(window_totals.get("hourly_costs", []))
        self._set_icon(icon_template, icon_window_totals or {}, mtd_cost, budget)
        self._update_conditional_sections(window_totals, recent, cfg, insights, label)

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

        if otel_data is not None:
            self._update_otel_sections(otel_data, s)
            self._otel_data_available = otel_data.available
            if otel_data.available and otel_data.otel_usage is not None:
                self._otel_cost_1d = otel_data.otel_usage.cost_24h
            else:
                self._otel_cost_1d = 0.0
        else:
            self._otel_data_available = False

    def _clear_otel_headers(self) -> None:
        for hdr in (
            self._hdr_otel_usage, self._hdr_otel_models, self._hdr_otel_meta,
            self._hdr_hooks, self._hdr_tools, self._hdr_code,
            self._hdr_skills, self._hdr_session_patterns,
        ):
            hdr.title = ""

    def _update_otel_sections_a(self, otel_data: OtelDisplayData, s: dict) -> None:
        if not otel_data.available:
            self._clear_otel_headers()
            return
        if s.get("otel_usage", {}).get("enabled", False):
            ou = otel_data.otel_usage
            otel_label, _ = _OTEL_WINDOWS[self._otel_window_idx]
            otel_next_label, _ = _OTEL_WINDOWS[(self._otel_window_idx + 1) % len(_OTEL_WINDOWS)]
            self._hdr_otel_usage.title = f"-- OTel Usage ({otel_label}) [click: {otel_next_label}] --"
            _, current_otel_window = _OTEL_WINDOWS[self._otel_window_idx]
            cost_suffix = "" if current_otel_window == "7d" else f"  (7d: ${ou.cost_7d:.2f})"
            self._otel_usage_rows[0].title = f"  Cost: ${ou.cost_24h:.2f}{cost_suffix}"
            self._otel_usage_rows[1].title = f"  Active: {ou.active_hours_24h:.1f}h"
            self._otel_usage_rows[2].title = f"  Tokens: {ou.total_tokens_24h // 1_000_000}M  in:{ou.input_tokens_24h // 1000}k  out:{ou.output_tokens_24h // 1000}k"
            top_model_str = ", ".join(f"{mdl.split('.')[-1]} ${cost:.2f}" for mdl, cost in ou.model_cost_breakdown[:2])
            self._otel_usage_rows[3].title = "  Models: " + top_model_str
        if s.get("otel_models", {}).get("enabled", False):
            om = otel_data.otel_models
            self._hdr_otel_models.title = "-- OTel Models --"
            for idx, (mdl, cost, toks) in enumerate(om.model_rows[:4]):
                short = mdl.split(".")[-1] if "." in mdl else mdl
                self._otel_model_rows[idx].title = f"  {short}  ${cost:.2f}  {toks // 1000}k tok"
            for idx in range(len(om.model_rows), 4):
                self._otel_model_rows[idx].title = ""
        if s.get("otel_meta", {}).get("enabled", False):
            ms = otel_data.meta_stats
            self._hdr_otel_meta.title = "-- Meta --"
            self._otel_meta_rows[0].title = f"  ${ms.cost_per_active_hour:.2f}/hr active"
            self._otel_meta_rows[1].title = f"  ${ms.cost_per_loc_added:.4f}/line  ${ms.cost_per_commit:.2f}/commit"
            self._otel_meta_rows[2].title = f"  Cache hit: {ms.cache_hit_rate_pct:.0f}%"
            self._otel_meta_rows[3].title = f"  {ms.total_tokens_24h // 1_000_000}M tokens today"
        if s.get("otel_hooks", {}).get("enabled", False):
            hk = otel_data.hook_health
            self._hdr_hooks.title = "-- Hook Health --"
            self._hook_rows[0].title = f"  Fired: {hk.hooks_fired_today}  Blocking: {hk.blocking_count}  Errors: {hk.error_count}"
            self._hook_rows[1].title = f"  Avg latency: {hk.avg_hook_latency_ms:.0f}ms"
            top_hooks = ", ".join(hk.hook_names[:2])
            self._hook_rows[2].title = "  Top hooks: " + top_hooks
            self._hook_rows[3].title = ""

    def _update_otel_sections_b(self, otel_data: OtelDisplayData, s: dict) -> None:
        if not otel_data.available:
            return
        if s.get("otel_tools", {}).get("enabled", False):
            ta = otel_data.tool_activity
            self._hdr_tools.title = "-- Tool Activity --"
            self._tool_rows[0].title = f"  Calls: {ta.tool_calls_today}  Accept: {ta.accept_rate_pct:.0f}%"
            top2 = ", ".join(t for t, _ in ta.top_tools[:2])
            self._tool_rows[1].title = "  Top tools: " + top2
            self._tool_rows[2].title = f"  Bash err rate: {ta.bash_error_rate_pct:.0f}%  ({ta.tool_error_count} total errors)"
            self._tool_rows[3].title = f"  Avg in: {ta.avg_input_bytes:.0f}B  out: {ta.avg_output_bytes:.0f}B"
            self._tool_rows[4].title = ""
        if s.get("otel_code", {}).get("enabled", False):
            ci = otel_data.code_impact
            self._hdr_code.title = "-- Code Impact --"
            self._code_rows[0].title = f"  Lines: +{ci.lines_added_today:,} / -{ci.lines_removed_today:,}  Commits: {ci.commits_today}"
            langs = ", ".join(f"{lang} \xd7{cnt}" for lang, cnt in ci.top_languages[:3])
            self._code_rows[1].title = "  Languages: " + langs
            self._code_rows[2].title = f"  Compactions: {ci.compaction_count}"
            self._code_rows[3].title = f"  Tokens saved: {ci.tokens_saved_by_compaction:,}"
            self._code_rows[4].title = ""
        if s.get("otel_skills", {}).get("enabled", False):
            sk = otel_data.skills
            self._hdr_skills.title = "-- Skills --"
            top_sk = ", ".join(f"{name} \xd7{cnt}" for name, cnt in sk.top_skills[:3])
            self._skill_rows[0].title = "  Today: " + top_sk
            self._skill_rows[1].title = f"  Total invocations: {sk.skills_invoked_today}"
        if s.get("otel_sessions", {}).get("enabled", False):
            sp = otel_data.session_patterns
            self._hdr_session_patterns.title = "-- Session Patterns --"
            mix = ", ".join(f"{mdl.split('-')[1] if '-' in mdl else mdl} \xd7{cnt}" for mdl, cnt in sp.model_mix[:2])
            self._session_pattern_rows[0].title = "  Models: " + mix
            self._session_pattern_rows[1].title = f"  Agent calls: {sp.agent_call_pct:.0f}%  Prompts: {sp.prompts_today}"
            effort = ", ".join(f"{eff}:{cnt}" for eff, cnt in sp.effort_mix.items() if cnt)
            self._session_pattern_rows[2].title = "  Effort: " + effort

    def _update_otel_sections(self, otel_data: OtelDisplayData, s: dict) -> None:
        self._update_otel_sections_a(otel_data, s)
        self._update_otel_sections_b(otel_data, s)

    def _update_model_rows(self, models: dict[str, float]) -> None:
        ranked = sorted(models.items(), key=lambda kv: kv[1], reverse=True)
        for idx, row in enumerate(self._model_rows):
            if idx < len(ranked):
                name, cost = ranked[idx]
                row.title = f"  {_model_short(name):<18}  {_format_cost(cost)}"
            else:
                row.title = "  -" if ranked else "  (none)"

    def _update_session_rows(self, recent: list[SessionSummary], label: str) -> None:
        self._hdr_sessions.title = f"-- Active Sessions ({label}) --"
        now_ts = time.time()
        for idx, row in enumerate(self._session_rows):
            if idx < len(recent):
                s = recent[idx]
                age_ref = s.end_time or s.start_time
                age_secs = now_ts - age_ref.timestamp()
                row.title = (
                    f"  {_project_short(s)}"
                    f"  {_format_cost(s.total_cost, s.cost_is_estimated)}"
                    f"  {_format_tokens(s.input_tokens)}in/{_format_tokens(s.output_tokens)}out"
                    f"  {_age_str(age_secs)}"
                )
            else:
                row.title = "  -"
        rest = recent[self._DETAIL_SESSIONS:]
        if rest:
            self._session_more.title = f"  ...and {len(rest)} more  {_format_cost(sum(s.total_cost for s in rest))}"
        elif recent:
            self._session_more.title = "  -"
        else:
            self._session_more.title = f"  no sessions in {label}"

    def _render_insights(self, payload: dict | None, max_tips: int = _MAX_TIPS_LIMIT) -> None:
        if payload is None:
            self._hdr_insights.title = "-- Insights --"
            self._info_insights_summary.title = "  ccpulse data not available"
            for idx, row in enumerate(self._insights_tip_rows):
                row.title = f"  insights_tip_{idx + 1}"
                row.hidden = True
                self._insights_tip_hints[idx] = {}
            return

        project_short = self._project_label_from_path(payload.get("project_path"))
        self._hdr_insights.title = (
            f"-- Insights ({project_short}) --" if project_short
            else "-- Insights (current session) --"
        )
        eff = _safe_float(payload.get("efficiency_score"), 0.0)
        ws = payload.get("waste_summary") if isinstance(payload.get("waste_summary"), dict) else {}
        cost = _safe_float(payload.get("cost_usd"), 0.0)
        cost_est = bool(payload.get("cost_is_estimated", False))
        avoid = _safe_int(ws.get("avoidable"), 0)
        review = _safe_int(ws.get("review"), 0)
        self._info_insights_summary.title = (
            f"  Eff {eff:.0f}%  |  {avoid} avoid / {review} review  |  {_format_cost(cost, cost_est)}"
        )

        raw_tips = payload.get("tips") or []
        tips = [t for t in raw_tips if isinstance(t, dict)][:max_tips]
        for idx, row in enumerate(self._insights_tip_rows):
            self._render_tip_row(idx, row, tips)

    def _render_tip_row(self, idx: int, row: object, tips: list[dict]) -> None:
        if idx < len(tips):
            t = tips[idx]
            icon = "✗" if t.get("severity") == "avoidable" else "⚠"
            count = _safe_int(t.get("count"), 0)
            reason = str(t.get("waste_reason") or "?")
            tip_cost = _safe_float(t.get("cost_impact"), 0.0)
            row.title = f"  {icon} {count}× {reason}  ·  saves ~${tip_cost:.2f}"  # type: ignore[union-attr]
            row.hidden = False  # type: ignore[union-attr]
            self._insights_tip_hints[idx] = {
                "waste_reason": reason,
                "claude_rule": str(t.get("claude_rule") or ""),
                "fix_hint": str(t.get("fix_hint") or ""),
            }
        else:
            row.hidden = True  # type: ignore[union-attr]
            self._insights_tip_hints[idx] = {}

    @staticmethod
    def _project_label_from_path(project_path: str | None) -> str:
        if not project_path:
            return ""
        name = Path(project_path).name
        parts = [p for p in name.split("-") if p]
        return parts[-1][:32] if parts else ""

    def _make_tip_click_handler(self, idx: int):  # type: ignore[no-untyped-def]
        def _handler(_sender: object) -> None:  # noqa: ARG001
            data = self._insights_tip_hints[idx] if idx < len(self._insights_tip_hints) else {}
            rule = data.get("claude_rule") or ""
            reason = data.get("waste_reason") or "tip"
            if not rule:
                fix = data.get("fix_hint") or ""
                if fix:
                    self._copy_to_clipboard(fix)
                    self._notify("Fix copied", fix)
                return
            response = rumps.alert(
                title=f"CLAUDE.md rule for {reason}",
                message=(
                    f"{rule}\n\n"
                    "Copy this rule, then paste it into your CLAUDE.md "
                    "(global ~/.claude/CLAUDE.md or project-level)."
                ),
                ok="Copy", cancel="Close",
            )
            if response == 1:
                self._copy_to_clipboard(rule)
                self._notify("Rule copied", rule)
        return _handler

    @staticmethod
    def _notify(title: str, body: str) -> None:
        try:
            rumps.notification(title=title, subtitle="", message=body[:200])
        except Exception:  # nosec B110 - notification failure is non-fatal
            pass

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        if _HAS_APPKIT:
            try:
                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(text, NSPasteboardTypeString)
                return
            except Exception:  # nosec B110 - AppKit clipboard failure falls through to pbcopy
                pass
        try:
            import subprocess as _sp
            _sp.run(["pbcopy"], input=text.encode(), check=False)  # nosec B603 B607 - fixed macOS system utility, no dynamic args
        except Exception:  # nosec B110 - pbcopy failure is non-fatal; clipboard update is best-effort
            pass

    def _on_configure(self, _sender: object) -> None:  # noqa: ARG002
        cfg = _load_config()
        win = rumps.Window(
            title="ClaudeStats — Configure",
            message=(
                "Edit settings below.\n"
                "Sections: on/off  •  Rows: on/off  •  max_tips: 1–10\n"
                "Changes take effect immediately on Save."
            ),
            default_text=_config_to_text(cfg),
            ok="Save", cancel="Cancel", dimensions=(340, 220),
        )
        response = win.run()
        if response.clicked != 1:
            return
        updated, rejected = _parse_config_text(response.text, cfg)
        try:
            _save_config(updated)
        except Exception as exc:  # nosec B110 - save failure surfaced to user via alert
            rumps.alert(title="Save failed", message=str(exc))
            return
        self._rebuild_menu(updated)
        self._last_cfg = updated
        self._refresh(None)
        if rejected:
            preview = "\n".join(f"  • {line}" for line in rejected[:8])
            extra = f"\n  …and {len(rejected) - 8} more" if len(rejected) > 8 else ""
            rumps.alert(
                title="Some settings weren't applied",
                message=(
                    "These lines were saved but ignored because the value "
                    "failed validation or the key isn't recognized:\n\n"
                    f"{preview}{extra}\n\nOther settings were saved normally."
                ),
            )

    def _on_toggle_login_item(self, _sender: object) -> None:  # noqa: ARG002
        if not _login_item.is_bundle_mode():
            rumps.alert(title="Start at Login", message=(
                "This feature requires the packaged ClaudeStats app. "
                "Launch the installed .app bundle, then try again."
            ))
            return
        try:
            if _login_item.is_enabled():
                _login_item.disable()
            else:
                _login_item.enable()
        except (OSError, RuntimeError) as exc:
            rumps.alert(title="Start at Login", message=f"Could not update login item: {exc}")
        self._btn_login_item.state = 1 if _login_item.is_enabled() else 0

    def _on_clear(self, _sender: object) -> None:  # noqa: ARG002
        response = rumps.alert(
            title="Clear old sessions",
            message=(
                "Delete all .jsonl session files older than 30 days "
                "from ~/.claude/projects/?\n\nThis cannot be undone."
            ),
            ok="Delete", cancel="Cancel",
        )
        if response != 1:
            return
        cutoff = time.time() - _STORAGE_WARN_DAYS * 86400
        deleted = 0
        try:
            for project_dir in _PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                for jsonl_file in project_dir.glob("*.jsonl"):
                    if jsonl_file.stat().st_mtime < cutoff:
                        jsonl_file.unlink()
                        deleted += 1
                try:
                    next(project_dir.iterdir())
                except StopIteration:
                    project_dir.rmdir()
        except Exception as exc:  # nosec B110 - partial cleanup failure is reported via notification
            rumps.notification(title="Clear failed", subtitle="Could not delete all files", message=str(exc))
            return
        rumps.notification(
            title="Sessions cleared",
            subtitle=f"{deleted} file{'s' if deleted != 1 else ''} deleted",
            message="Session files older than 30 days have been removed.",
        )
        self._refresh(None)
