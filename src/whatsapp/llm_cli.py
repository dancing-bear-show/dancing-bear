from __future__ import annotations

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="whatsapp",
    app_title="WhatsApp",
    purpose="Local WhatsApp ChatStorage search helpers",
    agentic_module="whatsapp.agentic",
    familiar_extended_steps=[
        "./bin/whatsapp search --contains school --limit 20",
    ],
    policies_fallback=(
        "policies:\n"
        "  style:\n"
        "    - Keep CLI stable; prefer dry-run flows\n"
        "  tests:\n"
        "    - Add lightweight unittest for new CLI surfaces\n"
    ),
    prog="llm-whatsapp",
    description="WhatsApp Assistant LLM utilities (inventory, familiar, policies, agentic, domain-map)",
)


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
