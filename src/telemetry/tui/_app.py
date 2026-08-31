"""TelemetryTranscriptsApp — interactive Textual dashboard and run_live entry point."""

from datetime import timedelta
from pathlib import Path

from core.date_utils import now_utc

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer

from telemetry.blame import BlameEngine
from telemetry.classify import ClassifyEngine
from telemetry.models import AgentSummary, SessionEvent, Tip, ToolStats
from telemetry.providers.transcript import TranscriptProvider
from telemetry.rules import load_rules
from telemetry.tips import TipsEngine
from telemetry.tui._constants import _CLASS_SYMBOLS, _WASTE_TAGS
from telemetry.tui._formatters import _bar, _event_desc, _format_cost
from telemetry.tui._renderers import (
    _agent_detail,
    _tip_detail,
    _tool_event_detail,
    _tool_stat_detail,
)
from telemetry.tui._summary import SummaryConfig, compute_summary
from telemetry.tui._widgets import (
    APP_CSS,
    _DetailModal,
    FooterInfo,
    HeaderPanel,
    SessionPickerScreen,
    TipsPanel,
)


class TelemetryTranscriptsApp(App):
    """Interactive telemetry-transcripts TUI dashboard."""

    CSS = APP_CSS
    TITLE = "telemetry-transcripts"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "switch_session", "Switch Session"),
    ]

    def __init__(
        self,
        session_id: str | None = None,
        refresh: float = 2.0,
        rules_path: str | None = None,
    ) -> None:
        super().__init__()
        self._rules = load_rules(rules_path)
        self._classify = ClassifyEngine(self._rules)
        self._blame = BlameEngine(self._rules)
        self._tips_engine = TipsEngine(self._rules)
        self._transcript = TranscriptProvider()
        self._refresh = refresh
        self._session_id = session_id
        self._session_file: Path | None = None
        self._all_events: list[SessionEvent] = []
        self._all_agents: list[AgentSummary] = []
        self._tool_stats_list: list[ToolStats] = []
        self._tips_list: list[Tip] = []
        self._last_event_count: int = 0
        self._last_tool_stats_key: str = ""
        self._last_agents_key: str = ""
        self._last_tips_key: str = ""

    def compose(self) -> ComposeResult:
        yield HeaderPanel(id="header")
        yield DataTable(id="tools-table")
        yield DataTable(id="agents-table")
        yield DataTable(id="timeline")
        yield DataTable(id="tips-table")
        yield TipsPanel(id="tips-empty")
        yield FooterInfo(id="footer-info")
        yield Footer()

    def on_mount(self) -> None:  # pragma: no cover - query_one needs a mounted DOM
        if self._session_id is None:
            self._session_id = self._transcript.get_current_session_id()
        if self._session_id:
            self._session_file = self._transcript.find_session_file(
                self._session_id
            )

        tools_tbl = self.query_one("#tools-table", DataTable)
        tools_tbl.cursor_type = "row"
        tools_tbl.add_columns("Tool", "Calls", "Cost", "Rel. Cost", "Avoid")

        agents_tbl = self.query_one("#agents-table", DataTable)
        agents_tbl.cursor_type = "row"
        agents_tbl.add_columns(
            "Description", "Type", "Model", "Duration", "Tools", "Cost"
        )

        timeline = self.query_one("#timeline", DataTable)
        timeline.cursor_type = "row"
        timeline.add_columns("Time", "St", "Tool", "Target", "Cost", "Tag")

        tips_tbl = self.query_one("#tips-table", DataTable)
        tips_tbl.cursor_type = "row"
        tips_tbl.add_columns("Sev", "Source", "Issue", "Count", "Cost")

        self._refresh_data()
        self.set_interval(self._refresh, self._refresh_data)

    # ------------------------------------------------------------------
    # Data refresh — panels always show FULL session data
    # ------------------------------------------------------------------

    def _refresh_data(self) -> None:  # pragma: no cover - query_one needs a mounted DOM
        if not self._session_file or not self._session_id:
            self.query_one("#header", HeaderPanel).update(
                "[red]No session found. Press 's' to select.[/]"
            )
            return

        try:
            events, agents = self._transcript.parse_session_with_agents(
                self._session_file
            )
        except Exception:
            return

        self._all_events = events
        self._all_agents = agents

        self._classify.classify(events)
        self._blame.attribute(events)

        project_path = (
            str(self._session_file.parent) if self._session_file else None
        )
        summary = compute_summary(
            events, agents,
            SummaryConfig(self._session_id, project_path, cost_is_estimated=True),
        )

        tips = self._tips_engine.generate(events, max_tips=5)

        self.query_one("#header", HeaderPanel).update_summary(summary)
        self._tips_list = tips
        self._refresh_tips_table(tips)
        self.query_one("#footer-info", FooterInfo).update_info(
            self._session_id, summary.total_events,
            self._refresh, summary.cost_is_estimated,
        )

        self._tool_stats_list = sorted(
            summary.tool_stats.values(), key=lambda s: s.cost, reverse=True
        )[:8]
        self._refresh_tools_table()

        self._refresh_agents_table(agents)

        tool_count = sum(
            1 for e in events if e.event_type == "tool_use" and e.tool_name
        )
        if tool_count != self._last_event_count:
            self._refresh_timeline(events)
            self._last_event_count = tool_count

    def _refresh_tools_table(self) -> None:
        key = "|".join(
            f"{s.tool_name}:{s.count}:{s.cost:.4f}:{s.avoidable_count}"
            for s in self._tool_stats_list
        )
        if key == self._last_tool_stats_key:
            return
        self._last_tool_stats_key = key

        tbl = self.query_one("#tools-table", DataTable)
        tbl.clear()
        max_cost = self._tool_stats_list[0].cost if self._tool_stats_list else 1.0
        for stat in self._tool_stats_list:
            frac = stat.cost / max_cost if max_cost > 0 else 0.0
            avoid_str = str(stat.avoidable_count) if stat.avoidable_count else "—"
            tbl.add_row(
                stat.tool_name, str(stat.count),
                f"${stat.cost:.3f}", _bar(frac, 8), avoid_str,
            )

    def _refresh_agents_table(self, agents: list[AgentSummary]) -> None:
        key = "|".join(f"{a.agent_id}:{a.total_tool_uses}" for a in agents)
        if key == self._last_agents_key:
            return
        self._last_agents_key = key

        tbl = self.query_one("#agents-table", DataTable)
        tbl.clear()
        for a in agents:
            desc = (a.description[:25] if a.description else "—")
            model_short = a.model.split("/")[-1] if a.model else "—"
            tbl.add_row(
                desc, a.agent_type, model_short,
                f"{a.duration_ms / 1000:.1f}s",
                str(a.total_tool_uses),
                _format_cost(a.cost_usd, a.cost_is_estimated),
            )

    def _refresh_timeline(self, events: list[SessionEvent]) -> None:
        timeline = self.query_one("#timeline", DataTable)
        timeline.clear()
        tool_events = [
            e for e in events
            if e.event_type == "tool_use" and e.tool_name
        ]
        for evt in tool_events:
            ts = evt.timestamp.strftime("%H:%M:%S")
            cls = evt.classification or "neutral"
            sym = _CLASS_SYMBOLS.get(cls, "○")
            tool = (evt.tool_name or "")[:10]
            desc = _event_desc(evt)
            cost_str = f"${evt.cost_usd:.4f}" if evt.cost_usd else ""
            tag = ""
            if evt.waste_reason:
                tag = _WASTE_TAGS.get(
                    evt.waste_reason, evt.waste_reason[:4].upper()
                )
            elif evt.success is False:
                tag = "FAIL"
            timeline.add_row(
                ts, sym, tool, desc, cost_str, tag,
                key=str(evt.sequence),
            )

    def _refresh_tips_table(self, tips: list[Tip]) -> None:
        key = "|".join(f"{t.waste_reason}:{t.count}:{t.cost_impact:.4f}" for t in tips)
        if key == self._last_tips_key:
            return
        self._last_tips_key = key

        tbl = self.query_one("#tips-table", DataTable)
        empty = self.query_one("#tips-empty", TipsPanel)
        tbl.clear()
        if not tips:
            tbl.display = False
            empty.display = True
            empty.update_empty()
            return
        tbl.display = True
        empty.display = False
        for tip in tips:
            sym = "✗" if tip.severity == "avoidable" else "⚠"
            source = tip.blame_target.name if tip.blame_target else "session"
            tbl.add_row(
                sym, source[:20], tip.waste_reason,
                str(tip.count), f"${tip.cost_impact:.2f}",
            )

    # ------------------------------------------------------------------
    # Enter key — contextual detail popup
    # ------------------------------------------------------------------

    def _show_timeline_detail(self, row_idx: int) -> None:
        tool_events = [
            e for e in self._all_events if e.event_type == "tool_use" and e.tool_name
        ]
        if row_idx < len(tool_events):
            self.push_screen(_DetailModal("Event Detail", _tool_event_detail(tool_events[row_idx])))

    def _show_tools_detail(self, row_idx: int) -> None:
        if row_idx < len(self._tool_stats_list):
            stat = self._tool_stats_list[row_idx]
            self.push_screen(_DetailModal("Tool Detail", _tool_stat_detail(stat, self._all_events)))

    def _show_agents_detail(self, row_idx: int) -> None:
        if row_idx < len(self._all_agents):
            self.push_screen(_DetailModal("Agent Detail", _agent_detail(self._all_agents[row_idx])))

    def _show_tips_detail(self, row_idx: int) -> None:
        if row_idx < len(self._tips_list):
            self.push_screen(_DetailModal("Tip Detail", _tip_detail(self._tips_list[row_idx])))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show detail modal based on which table is focused."""
        table_id = event.data_table.id
        row_idx = event.cursor_row
        if row_idx is None or row_idx < 0:
            return

        dispatch = {
            "timeline": self._show_timeline_detail,
            "tools-table": self._show_tools_detail,
            "agents-table": self._show_agents_detail,
            "tips-table": self._show_tips_detail,
        }
        handler = dispatch.get(table_id or "")
        if handler:
            handler(row_idx)

    # ------------------------------------------------------------------
    # Session switching
    # ------------------------------------------------------------------

    def action_switch_session(self) -> None:
        since = now_utc() - timedelta(days=30)
        sessions = self._transcript.get_sessions(since=since)
        if not sessions:
            self.notify("No sessions found", severity="warning")
            return

        def on_dismiss(session_id: str | None) -> None:
            if session_id:
                self._session_id = session_id
                self._session_file = self._transcript.find_session_file(
                    session_id
                )
                self._last_event_count = 0  # force timeline repopulate
                self._refresh_data()

        self.push_screen(SessionPickerScreen(sessions), on_dismiss)


def run_live(  # pragma: no cover - blocks on the Textual event loop
    session_id: str | None = None,
    refresh: float = 2.0,
    rules_path: str | None = None,
) -> None:
    """Run the interactive TUI dashboard."""
    app = TelemetryTranscriptsApp(
        session_id=session_id, refresh=refresh, rules_path=rules_path,
    )
    app.run()
