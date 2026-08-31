from __future__ import annotations

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="maker",
    app_title="Maker",
    purpose="Utility generators and print helpers",
    agentic_module="maker.agentic",
    prog="llm-maker",
    description="Maker LLM utilities (agentic, domain-map, derive-all)",
)


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
