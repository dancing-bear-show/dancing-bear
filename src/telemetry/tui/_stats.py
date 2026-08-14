"""Live stats renderer (_StatsRenderer), run_stats, and print_summary entry points."""

from rich.console import Console
from rich.panel import Panel

from telemetry.blame import BlameEngine
from telemetry.classify import ClassifyEngine
from telemetry.providers.transcript import TranscriptProvider
from telemetry.rules import load_rules
from telemetry.tips import TipsEngine
from telemetry.tui._renderers import (
    _print_agents_panel,
    _print_tool_stats_panel,
    _render_header_text,
    _render_stats_compact,
    _render_stats_panel,
    _render_timeline_line,
    _render_tips_text,
)
from telemetry.tui._summary import SummaryConfig, compute_summary


class _StatsRenderer:
    """Holds live-stats state and builds Rich renderables for each refresh tick."""

    def __init__(
        self,
        session_id: str | None,
        compact: bool,
        classify_engine: ClassifyEngine,
        blame_engine: BlameEngine,
        transcript: TranscriptProvider,
    ) -> None:
        from rich.text import Text  # noqa: PLC0415 - local import to avoid top-level dep
        self._text_cls = Text
        self.compact = compact
        self.classify_engine = classify_engine
        self.blame_engine = blame_engine
        self.transcript = transcript
        self.resolved_session_id = session_id or transcript.get_current_session_id()
        self.session_file = (
            transcript.find_session_file(self.resolved_session_id)
            if self.resolved_session_id else None
        )

    def _resolve_session(self) -> None:
        """Lazily discover the current session if not yet known."""
        if self.resolved_session_id is None:
            self.resolved_session_id = self.transcript.get_current_session_id()
        if self.resolved_session_id and self.session_file is None:
            self.session_file = self.transcript.find_session_file(self.resolved_session_id)

    def build(self) -> object:
        """Return a Rich renderable for the current session state."""
        self._resolve_session()

        if not self.session_file or not self.resolved_session_id:
            waiting = self._text_cls("Waiting for session…", style="dim")
            return Panel(waiting, title="[bold]stats[/]", border_style="dim")

        try:
            events, agents = self.transcript.parse_session_with_agents(self.session_file)
        except Exception:
            return Panel(
                self._text_cls("Error reading session.", style="red"),
                title="[bold]stats[/]", border_style="red",
            )

        self.classify_engine.classify(events)
        self.blame_engine.attribute(events)

        project_path = str(self.session_file.parent)
        summary = compute_summary(
            events, agents,
            SummaryConfig(self.resolved_session_id, project_path, cost_is_estimated=True),
        )

        if self.compact:
            return self._text_cls.from_markup(_render_stats_compact(summary))
        return _render_stats_panel(summary)


def run_stats(  # pragma: no cover - blocks on a Rich Live refresh loop
    session_id: str | None = None,
    refresh: float = 2.0,
    compact: bool = False,
    rules_path: str | None = None,
) -> None:
    """Run the compact live stats panel using Rich Live (no Textual)."""
    import time
    from rich.live import Live

    rules = load_rules(rules_path)
    renderer = _StatsRenderer(
        session_id=session_id,
        compact=compact,
        classify_engine=ClassifyEngine(rules),
        blame_engine=BlameEngine(rules),
        transcript=TranscriptProvider(),
    )
    console = Console()

    try:
        with Live(
            renderer.build(),
            console=console,
            refresh_per_second=1,
            transient=False,
        ) as live:
            while True:
                time.sleep(refresh)
                live.update(renderer.build())
    except KeyboardInterrupt:
        pass


def print_summary(
    session_id: str | None = None,
    rules_path: str | None = None,
) -> None:
    """Print a one-shot static summary and exit."""
    rules = load_rules(rules_path)
    classify_engine = ClassifyEngine(rules)
    blame_engine = BlameEngine(rules)
    tips_engine = TipsEngine(rules)
    transcript = TranscriptProvider()
    console = Console()

    if session_id is None:
        session_id = transcript.get_current_session_id()
        if session_id is None:
            console.print("[red]No active session found.[/]")
            return

    session_file = transcript.find_session_file(session_id)
    if session_file is None:
        console.print(f"[red]Session file not found for: {session_id}[/]")
        return

    project_path = str(session_file.parent) if session_file else None

    events, agents = transcript.parse_session_with_agents(session_file)
    classify_engine.classify(events)
    blame_engine.attribute(events)

    summary = compute_summary(
        events, agents,
        SummaryConfig(session_id, project_path, cost_is_estimated=True),
    )
    tips = tips_engine.generate(events, max_tips=5)

    console.print(Panel(_render_header_text(summary), title="[bold]Session[/]", border_style="blue"))
    _print_tool_stats_panel(console, summary)
    _print_agents_panel(console, agents)

    tool_events = [e for e in events if e.event_type == "tool_use" and e.tool_name]
    lines = [_render_timeline_line(evt) for evt in tool_events[-20:]]
    console.print(Panel(
        "\n".join(lines) or "[dim]No events[/]",
        title="[bold]Timeline[/]", border_style="green",
    ))

    if tips:
        console.print(Panel(_render_tips_text(tips), title="[bold]Tips[/]", border_style="red"))
