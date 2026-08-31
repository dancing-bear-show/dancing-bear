from __future__ import annotations

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="calendar",
    app_title="Calendar",
    purpose="Outlook calendars + Gmail scans → plans",
    agentic_module="calendars.agentic",
    familiar_compact_steps=[
        "./bin/calendar --agentic",
        "./bin/llm-calendar agentic --stdout",
    ],
    familiar_extended_steps=[
        "./bin/calendar --agentic",
        "./bin/llm-calendar agentic --stdout",
        "./bin/mail-assistant --profile outlook_personal outlook auth.ensure || true",
        "./bin/mail-assistant --profile outlook_personal outlook auth.validate || true",
    ],
    policies_fallback=(
        "policies:\n"
        "  style:\n"
        "    - Keep CLI stable; add only\n"
        "  tests:\n"
        "    - Add lightweight unittest for new CLI\n"
    ),
    description="Calendar LLM utilities (inventory, familiar, policies, agentic, domain-map)",
)


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
