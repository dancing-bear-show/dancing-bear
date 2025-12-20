from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from core.assistant import BaseAssistant
from maker.pipeline import (
    ConsoleProducer,
    ModuleResultProducer,
    ModuleRunnerProcessor,
    ToolCatalogConsumer,
    ToolCatalogFormatter,
    ToolRequest,
    ToolRequestConsumer,
)

assistant = BaseAssistant(
    "maker",
    "agentic: maker\npurpose: Utility generators (cards, TPU rods) and printer helpers",
)

ROOT = Path(__file__).resolve().parent

def _clean_module_args(args: List[str]) -> List[str]:
    if not args:
        return []
    if args and args[0] == "--":
        return args[1:]
    return args


def cmd_list_tools(args: argparse.Namespace) -> int:
    catalog = ToolCatalogConsumer(ROOT).consume()
    text = ToolCatalogFormatter().process(catalog)
    ConsoleProducer().produce(text)
    return 0


def _execute_tool(module: str, module_args: List[str]) -> int:
    request = ToolRequest(module=module, args=module_args)
    consumer = ToolRequestConsumer(request)
    processor = ModuleRunnerProcessor()
    envelope = processor.process(consumer.consume())
    ModuleResultProducer().produce(envelope)
    if envelope.payload is not None:
        return envelope.payload
    return 0 if envelope.ok() else 1


def _make_module_runner(module: str):
    def _runner(args: argparse.Namespace) -> int:
        module_args = _clean_module_args(getattr(args, "module_args", []))
        return _execute_tool(module, module_args)

    return _runner


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

    sp = sub.add_parser("list-tools", help="List available maker scripts")
    sp.set_defaults(func=cmd_list_tools)

    for cmd_name, module_path, help_text in (
        ("run-card", "maker.card.gen_snug_variants", "Run the snug card generator (forward args with --)"),
        ("run-tp-rod", "maker.tp_rod.gen_tp_rod", "Run the TP rod generator (forward args with --)"),
        ("print-send", "maker.print.send_to_printer", "Upload/print G-code (forward args with --)"),
    ):
        sp_cmd = sub.add_parser(cmd_name, help=help_text)
        sp_cmd.add_argument("module_args", nargs=argparse.REMAINDER)
        sp_cmd.set_defaults(func=_make_module_runner(module_path))

    return p


def main(argv: Optional[List[str]] = None) -> int:
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
