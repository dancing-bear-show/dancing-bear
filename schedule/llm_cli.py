from __future__ import annotations

import argparse
from typing import Optional

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="schedule",
    app_title="Schedule",
    purpose="Generate/verify/apply calendar plans (dry-run first)",
    agentic_module="schedule.agentic",
    familiar_compact_steps=[
        "./bin/schedule-assistant --help",
        "./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml --dry-run",
    ],
    familiar_extended_steps=[
        "./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml",
        "./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run",
        "./bin/schedule-assistant verify --plan out/schedule.plan.yaml --calendar 'Your Family' --from 2025-10-01 --to 2025-12-31",
    ],
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
