from __future__ import annotations

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="phone",
    app_title="Phone",
    purpose="Home Screen layout planning and manifest helpers",
    agentic_module="phone.agentic",
    familiar_compact_steps=[
        "./bin/phone --help",
    ],
    familiar_extended_steps=[
        "./bin/phone export-device --out out/ios.IconState.yaml",
        "./bin/phone iconmap --out out/ios.iconmap.json",
        "./bin/ios-iconmap-refresh",
        "./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml",
        "./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt",
    ],
    policies_fallback=(
        "policies:\n"
        "  style:\n"
        "    - Keep CLI stable; prefer plan→apply flows\n"
        "  tests:\n"
        "    - Add lightweight unittest for new CLI surfaces\n"
    ),
    prog="llm",
    description="Phone LLM utilities (inventory, familiar, policies, agentic, domain-map)",
)


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
