"""Agentic capsule builders for the GitHub CLI."""

from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser():
    # Import inside the function so a broken parser cannot poison module import;
    # cached_parser_loader below turns that into a swallowed None the shared
    # contract tests catch by asserting the capsule is substantial (>= 200B).
    from .cli import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def build_agentic_capsule() -> str:
    commands = [
        "resolve repo: ./bin/github repo",
        "fetch review threads: ./bin/github threads fetch --pr 123 --out threads.json",
        "reply to a thread: ./bin/github threads reply --thread THREAD_ID --body-file reply.md --run-id RUN --resolve",
        "get PR field: ./bin/github pr view --pr 123 --value headRefOid",
        "watch PR checks: ./bin/github pr checks --pr 123 --watch",
        "inline review comment: ./bin/github pr review-comment --pr 123 --path a.py --line 10 --body-file c.md",
    ]
    notes_body = "\n".join(
        [
            "- Every text body (reply, PR body, comment) is a file path (or `-` for stdin);",
            "  never an argv string. That is the whole point: review-derived text does",
            "  not pass through a shell.",
            "- Bodies never reach gh's argv: reply and review-comment fields go as JSON on",
            "  stdin (`gh api --input -`); PR bodies and comments via `--body-file -`.",
            "  An `@path`-looking body is sent as literal text, never read as a file.",
            "- `threads reply --run-id` re-fetches the full comment chain before posting;",
            "  only the authenticated actor's own marker yields `already_replied`; anyone",
            "  else's copy is reported as `forged_marker`. Quoted markers are stripped.",
            "- `threads reply` verifies the response payload (gh exits 0 on GraphQL errors),",
            "  and refuses to resolve when the reply did not verify.",
            "- `pr edit` reads the PR back and exits 1 when GitHub does not hold what was sent.",
            "- `pr checks` exits 0 while still pending/failing: read `bucket` in the JSON.",
            "- `threads fetch` exits 1 when a reported count does not match what came back;",
            "  it still writes the file (`truncated: true`) for inspection. Do not act on it.",
            "- `client()` scrubs `GITHUB_TOKEN` from the child env so a stale token cannot",
            "  silently override gh's keyring credentials.",
        ]
    )
    return _build_capsule(
        "github",
        "GitHub porcelain over core.github: review threads, PR view/edit/checks",
        commands,
        [("Notes", notes_body)] + _tree_and_flow_sections(_cli_tree(), None),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n"
        "- bin/github — CLI wrapper (routed through _router.py)\n"
        "- github_assistant/cli.py — argparse entry (threads, pr, run groups)\n"
        "- github_assistant/meta.py — AppMeta for the agentic surface\n"
        "- github_assistant/agentic.py — capsule + domain map\n"
        "- core/github/ — the tested access layer (client, threads, mutations, pulls, repo)\n"
        "- core/gh_cli.py — GhCLI/GhError; the single subprocess choke point",
        _cli_tree(),
        None,
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
