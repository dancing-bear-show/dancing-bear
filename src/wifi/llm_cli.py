from __future__ import annotations

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="wifi",
    app_title="Wi-Fi",
    purpose="Wi-Fi and LAN diagnostics",
    agentic_module="wifi.agentic",
    familiar_compact_steps=[
        "./bin/wifi --help",
    ],
    familiar_extended_steps=[
        "./bin/wifi --ping-count 8",
        "./bin/wifi --json --out out/wifi.diag.json",
    ],
    policies_fallback="policies:\n  style:\n    - Keep CLI flags stable; avoid new dependencies\n  tests:\n    - Add lightweight unittest for new probes and CLI output\n",
)


build_parser, main = llm_cli.bind_entrypoints(CONFIG)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
