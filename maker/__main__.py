from __future__ import annotations

"""Maker utilities CLI.

Commands:
  list-tools  — List available maker scripts
  card        — Generate snug-fit card variants
  tp-rod      — Generate TP rod model
  print-send  — Upload/print G-code
"""

import argparse
from pathlib import Path
from typing import Optional

from core.assistant import BaseAssistant
from .pipeline import (
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

ROOT = Path(__file__).resolve().parent


def cmd_list_tools(args: argparse.Namespace) -> int:
    """List available maker tool scripts."""
    catalog = ToolCatalogConsumer(ROOT).consume()
    text = ToolCatalogFormatter().process(catalog)
    ConsoleProducer().produce(text)
    return 0


def cmd_card(args: argparse.Namespace) -> int:
    """Generate snug-fit card variants for coin holders."""
    request = ToolRequest(module="maker.card.gen_snug_variants")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


def cmd_tp_rod(args: argparse.Namespace) -> int:
    """Generate TP rod model."""
    request = ToolRequest(module="maker.tp_rod.gen_tp_rod")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


def cmd_print_send(args: argparse.Namespace) -> int:
    """Upload/print G-code to printer."""
    request = ToolRequest(module="maker.print.send_to_printer")
    envelope = ToolRunnerProcessor().process(ToolRequestConsumer(request).consume())
    ToolResultProducer().produce(envelope)
    if envelope.ok():
        return 0
    return envelope.payload.return_code if envelope.payload else 1


def _emit_agentic(fmt: str, compact: bool) -> int:
    try:
        from .agentic import build_agentic_capsule

        print(build_agentic_capsule())
    except Exception:
        print("agentic: maker\npurpose: Utility generators and print helpers")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Maker utilities CLI")
    assistant.add_agentic_flags(p)
    sub = p.add_subparsers(dest="command")

    sp_list = sub.add_parser("list-tools", help="List available maker scripts")
    sp_list.set_defaults(func=cmd_list_tools)

    sp_card = sub.add_parser("card", help="Generate snug-fit card variants for coin holders")
    sp_card.set_defaults(func=cmd_card)

    sp_rod = sub.add_parser("tp-rod", help="Generate TP rod model")
    sp_rod.set_defaults(func=cmd_tp_rod)

    sp_print = sub.add_parser("print-send", help="Upload/print G-code to printer")
    sp_print.set_defaults(func=cmd_print_send)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
