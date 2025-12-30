"""Maker utilities CLI.

Commands:
  list-tools  — List available maker scripts
  card        — Generate snug-fit card variants
  tp-rod      — Generate TP rod model
  print-send  — Upload/print G-code
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from ..pipeline import (
    ConsoleProducer,
    ToolCatalogConsumer,
    ToolCatalogFormatter,
    ToolRequest,
    ToolRequestConsumer,
    ToolRunnerProcessor,
    ToolResultProducer,
)

assistant = BaseAssistant(
    "maker",
    "agentic: maker\npurpose: Utility generators (cards, TPU rods) and printer helpers",
)

app = CLIApp(
    "maker",
    "Maker utilities CLI",
    add_common_args=False,
)

ROOT = Path(__file__).resolve().parent.parent


def _emit_agentic(fmt: str, compact: bool) -> int:
    try:
        from ..agentic import build_agentic_capsule

        print(build_agentic_capsule())
    except Exception:
        print("agentic: maker\npurpose: Utility generators and print helpers")
    return 0


@app.command("list-tools", help="List available maker scripts")
def cmd_list_tools(args) -> int:
    """List available maker tool scripts."""
    catalog = ToolCatalogConsumer(ROOT).consume()
    text = ToolCatalogFormatter().process(catalog)
    ConsoleProducer().produce(text)
    return 0


@app.command("card", help="Generate snug-fit card variants for coin holders")
def cmd_card(args) -> int:
    """Generate snug-fit card variants for coin holders."""
    request = ToolRequest(module="maker.card.gen_snug_variants")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


@app.command("tp-rod", help="Generate TP rod model")
def cmd_tp_rod(args) -> int:
    """Generate TP rod model."""
    request = ToolRequest(module="maker.tp_rod.gen_tp_rod")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


@app.command("print-send", help="Upload/print G-code to printer")
def cmd_print_send(args) -> int:
    """Upload/print G-code to printer."""
    request = ToolRequest(module="maker.print.send_to_printer")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the Maker CLI."""
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)

    args = parser.parse_args(argv)

    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)

    cmd_func = getattr(args, "_cmd_func", None)
    if not cmd_func:
        parser.print_help()
        return 0

    return int(cmd_func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
