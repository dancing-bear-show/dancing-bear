from __future__ import annotations

import argparse
from typing import Optional

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="desk",
    app_title="Desk",
    purpose="Scan/plan/apply desk cleanup flows",
    agentic_module="desk.agentic",
    familiar_compact_steps=[
        "./bin/desk-assistant --help",
        "./bin/desk-assistant scan --help",
    ],
    familiar_extended_steps=[
        "./bin/desk-assistant scan --paths ~/Downloads ~/Desktop --duplicates --out out/desk.scan.yaml",
        "./bin/desk-assistant plan --config config/rules.yaml --out out/desk.plan.yaml",
        "./bin/desk-assistant apply --plan out/desk.plan.yaml --dry-run",
    ],
    policies_fallback="policies:\n  style:\n    - Keep CLI idempotent; default to dry-run\n  tests:\n    - Add smoke unittest for new commands\n",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
