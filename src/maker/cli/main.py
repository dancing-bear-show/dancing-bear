"""Maker utilities CLI.

Commands:
  list-tools  — List available maker scripts
  card        — Generate snug-fit card variants
  tp-rod      — Generate TP rod model
  print-send  — Upload/print G-code
"""

from __future__ import annotations

from pathlib import Path

from core.assistant import BaseAssistant
from ..meta import META
from core.cli_framework import CLIApp

from ..pipeline import (
    ToolCatalogProcessor,
    ToolCatalogProducer,
    ToolCatalogRequest,
    ToolCatalogRequestConsumer,
    ToolRequest,
    ToolRequestConsumer,
    ToolRunnerProcessor,
    ToolResultProducer,
)

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "maker",
    "Maker utilities CLI",
    add_common_args=False,
)

ROOT = Path(__file__).resolve().parent.parent


def _emit_agentic(fmt: str, compact: bool) -> int:
    try:
        from ..agentic import emit_agentic_context

        return emit_agentic_context(fmt, compact)
    except Exception:  # nosec B110 - graceful fallback when agentic module unavailable
        print(META.agentic_fallback)
    return 0


@app.command("list-tools", help="List available maker scripts")
def cmd_list_tools(args) -> int:
    """List available maker tool scripts."""
    request = ToolCatalogRequest(tools_root=ROOT)
    envelope = ToolCatalogProcessor().process(ToolCatalogRequestConsumer(request).consume())
    ToolCatalogProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def _run_tool(module: str) -> int:
    """Helper to run a maker tool and return exit code."""
    request = ToolRequest(module=module)
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok() and envelope.payload:
        return envelope.payload.return_code
    return 1


@app.command("card", help="Generate snug-fit card variants for coin holders")
def cmd_card(args) -> int:
    """Generate snug-fit card variants for coin holders."""
    return _run_tool("maker.card.gen_snug_variants")


@app.command("tp-rod", help="Generate TP rod model")
def cmd_tp_rod(args) -> int:
    """Generate TP rod model."""
    return _run_tool("maker.tp_rod.gen_tp_rod")


@app.command("print-send", help="Upload/print G-code to printer")
def cmd_print_send(args) -> int:
    """Upload/print G-code to printer."""
    return _run_tool("maker.print.send_to_printer")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Maker CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=_emit_agentic,
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
