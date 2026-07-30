from __future__ import annotations

import argparse
from typing import Optional

from core import llm_cli

CONFIG = llm_cli.make_domain_llm_module(
    app_id="resume",
    app_title="Resume",
    purpose="Extract, summarize, and render resumes",
    agentic_module="resume.agentic",
    familiar_compact_steps=[
        "./bin/resume-assistant --help",
        "./bin/resume-assistant extract --help",
    ],
    familiar_extended_steps=[
        "./bin/resume-assistant extract --linkedin data/linkedin.txt --resume data/resume.pdf --out out/profile.json",
        "./bin/resume-assistant summarize --data out/profile.json --seed seeds/general.yaml",
        "./bin/resume-assistant render --data out/profile.json --template templates/modern.yaml --profile default",
    ],
    policies_fallback="policies:\n  style:\n    - Keep CLI flags stable; prefer plan-first\n  tests:\n    - Add lightweight unittest for new surfaces\n",
)


def build_parser() -> argparse.ArgumentParser:
    return llm_cli.build_parser(CONFIG)


def main(argv: Optional[list[str]] = None) -> int:
    return llm_cli.run(CONFIG, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
