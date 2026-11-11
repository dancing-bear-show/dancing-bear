"""Agentic capsule builders for the agent helpers CLI."""

from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    tree_and_flow_sections as _tree_and_flow_sections,
)

_PURPOSE = "Structured checks for agent sessions: tests, AST/import/JSON validation, patch analysis, git ops"


def _load_parser():
    # Import inside the function so a broken parser cannot poison module import;
    # the shared contract tests assert the capsule is substantial.
    from .cli import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def build_agentic_capsule() -> str:
    commands = [
        "full suite: ./bin/agent-helpers run-tests",
        "scoped tests: ./bin/agent-helpers run-tests --paths tests/wifi_tests",
        "lint: ./bin/agent-helpers run-tests --tool lint",
        "types: ./bin/agent-helpers run-tests --tool typecheck",
        "symbols exist: ./bin/agent-helpers validate-imports --module core.process --symbols run_binary",
        "__all__ complete: ./bin/agent-helpers validate-ast --file src/core/process.py --all-exported",
        "JSON shape: ./bin/agent-helpers validate-json --file f.json --keys status,results --count results",
        "tally findings: ./bin/agent-helpers summarize-findings --input f.json --group-by severity",
        "diff facts: ./bin/agent-helpers analyze-patch --patch p.diff --extract added-functions",
        "worktrees: ./bin/agent-helpers git-ops --op worktree-list",
    ]
    notes_body = "\n".join(
        [
            "- Result commands print one JSON object and exit 0: read the verdict from the body",
            "  (`passed`, `status`, `overall`, `valid`). Exit 2 = usage error.",
            "- run-tests: `test` runs `make test` (or `unittest discover` per --paths); `lint` runs",
            "  `make lint`; `typecheck` runs `make typecheck-changed`. `test` is `passed: false`",
            "  unless output has `Ran N tests` with N > 0 (exit 0 alone is not evidence).",
            "- PYTHONPATH is replaced with this checkout's src/ for child processes.",
            "- validate-imports imports the module in-process; module side effects run.",
            "- Concern guides: use `./bin/workflow select-concerns`, not a helper here.",
        ]
    )
    return _build_capsule(
        "agent-helpers",
        _PURPOSE,
        commands,
        [("Notes", notes_body)] + _tree_and_flow_sections(_cli_tree(), None),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n"
        "- bin/agent-helpers — CLI wrapper (routed through _router.py)\n"
        "- agent_helpers/cli.py — argparse entry; one command per helper\n"
        "- agent_helpers/validate.py — imports / AST / JSON validators\n"
        "- agent_helpers/findings.py — summarize-findings\n"
        "- agent_helpers/patch.py — analyze-patch extractors\n"
        "- agent_helpers/git_ops.py — checkout / worktree ops\n"
        "- agent_helpers/checks.py — run-tests (make test/lint/typecheck-changed)\n"
        "- agent_helpers/repo.py — repo-root resolution",
        _cli_tree(),
        None,
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
