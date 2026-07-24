from __future__ import annotations

from pathlib import Path

from core.agentic import section as _section

FALLBACK_AGENTIC_HEADER: str = "agentic: maker\npurpose: Utility generators and print helpers"


def build_agentic_capsule() -> str:
    from .pipeline import scan_tools

    out: list[str] = []
    out.append("agentic: maker")
    out.append("purpose: Utility generators and print helpers")
    out.append("commands:")
    out.append("  - list tools: ./bin/maker list-tools")
    out.append("  - LLM domain map: ./bin/llm --app maker domain-map --stdout")
    out.append("  - example: python3 maker/card/gen_snug_variants.py --help")
    out.append("")
    tools = scan_tools(Path(__file__).resolve().parent)
    if tools:
        out.append(_section("Tools", "\n".join(f"- maker/{t}" for t in tools)))
    # Simple flows (illustrative)
    flows = [
        "- Cards\n  - Generate snug variants: python3 maker/card/gen_snug_variants.py --out out/cards\n",
        "- 3D Prints\n  - Generate TPU rod: python3 maker/tp_rod/gen_tp_rod.py --out out/rods\n  - Send to printer: python3 maker/print/send_to_printer.py --file out/rods/model.stl\n",
    ]
    out.append(_section("Flow Map", "\n".join(flows)))
    return "\n".join([s for s in out if s])


def build_domain_map() -> str:
    from .pipeline import scan_tools

    out: list[str] = []
    out.append("Top-Level\n- maker/card — card generators\n- maker/tp_rod — TPU rod generator\n- maker/print — printer helpers")
    tools = scan_tools(Path(__file__).resolve().parent)
    if tools:
        out.append(_section("Tools", "\n".join(f"- maker/{t}" for t in tools)))
    return "\n".join([s for s in out if s])


def emit_agentic_context() -> int:
    print(build_agentic_capsule())
    return 0
