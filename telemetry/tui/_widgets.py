"""Textual widgets, modals, and CSS for the telemetry TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, OptionList, Static
from textual.widgets.option_list import Option

from telemetry.models import SessionSummary

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

APP_CSS = """
HeaderPanel {
    height: auto;
    max-height: 8;
    padding: 0 1;
    border: solid $primary;
}
#tools-table {
    height: auto;
    max-height: 10;
    border: solid magenta;
}
#agents-table {
    height: auto;
    max-height: 12;
    border: solid yellow;
}
#timeline {
    height: 1fr;
    min-height: 6;
    border: solid green;
}
#tips-table {
    height: auto;
    max-height: 10;
    border: solid red;
}
TipsPanel {
    height: auto;
    max-height: 3;
    padding: 0 1;
    border: solid red;
}
FooterInfo {
    height: 1;
    dock: bottom;
    background: $surface;
    color: $text-muted;
    padding: 0 1;
}
SessionPickerScreen {
    align: center middle;
}
SessionPickerScreen OptionList {
    width: 80;
    max-height: 20;
    border: solid $primary;
    background: $surface;
}
_DetailModal {
    align: center middle;
}
#detail-scroll {
    width: 80;
    max-height: 80%;
    border: solid $primary;
    background: $surface;
}
#detail-content {
    width: 100%;
}

/* Focus styling — highlight the active section border */
DataTable:focus {
    border: heavy $accent;
}
"""

# ---------------------------------------------------------------------------
# Detail modal
# ---------------------------------------------------------------------------


class _DetailModal(ModalScreen):  # pragma: no cover
    """Generic detail modal — shows Rich markup and closes on Esc/Enter."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
    ]

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        from rich.panel import Panel  # noqa: PLC0415 - local import keeps Textual deps isolated

        with VerticalScroll(id="detail-scroll"):
            yield Static(
                Panel(self._content, title=f"[bold]{self._title}[/]",
                      border_style="cyan"),
                id="detail-content",
            )


# ---------------------------------------------------------------------------
# Session picker modal
# ---------------------------------------------------------------------------


class SessionPickerScreen(ModalScreen[str]):  # pragma: no cover
    """Modal for switching sessions."""

    BINDINGS = [Binding("escape", "dismiss_modal", "Close")]

    def __init__(self, sessions: list[SessionSummary]) -> None:
        super().__init__()
        self._sessions = sessions

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        for s in self._sessions[:50]:
            date_str = s.start_time.strftime("%Y-%m-%d %H:%M")
            project = (s.project_path or "-")[-40:]
            label = (
                f"{s.session_id[:12]}  {date_str}  "
                f"{project}  ${s.total_cost:.2f}"
            )
            options.append(Option(label, id=s.session_id))
        yield OptionList(*options, id="session-list")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self.dismiss(event.option.id)

    def action_dismiss_modal(self) -> None:
        self.dismiss("")


# ---------------------------------------------------------------------------
# Simple static widgets
# ---------------------------------------------------------------------------


class HeaderPanel(Static):  # pragma: no cover
    """Session summary header (not focusable)."""

    def update_summary(self, summary: SessionSummary) -> None:
        from telemetry.tui._renderers import _render_header_text  # noqa: PLC0415

        self.update(_render_header_text(summary))


class TipsPanel(Static):  # pragma: no cover
    """Tips display (not focusable, shown when no tips)."""

    def update_empty(self) -> None:
        self.update("[dim]No tips — session looks clean![/]")


class FooterInfo(Static):  # pragma: no cover
    """Bottom info bar."""

    def update_info(
        self, session_id: str, event_count: int, refresh: float,
        estimated: bool,
    ) -> None:
        est = " [estimated]" if estimated else ""
        self.update(
            f"Session: {session_id[:12]}  Events: {event_count}  "
            f"Refresh: {refresh}s  "
            f"[dim]Tab[/]=focus  [dim]Enter[/]=detail  "
            f"[dim]s[/]=switch  [dim]q[/]=quit{est}"
        )


# Re-export DataTable so _app.py can import it from one place
__all__ = [
    "APP_CSS",
    "_DetailModal",
    "DataTable",
    "FooterInfo",
    "HeaderPanel",
    "SessionPickerScreen",
    "TipsPanel",
]
