"""Agentic capsule builders for the memory CLI."""

from __future__ import annotations

from core.agentic import (
    build_capsule as _build_capsule,
    build_cli_tree as _core_build_cli_tree,
    build_domain_map as _core_build_domain_map,
    cached_parser_loader as _cached_parser_loader,
    tree_and_flow_sections as _tree_and_flow_sections,
)


def _load_parser():
    # Imported inside the function so a broken parser cannot poison module
    # import; the contract tests catch a swallowed None via capsule size.
    from .cli import app

    return app.build_parser()


_get_parser = _cached_parser_loader(_load_parser)


def _cli_tree() -> str:
    return _core_build_cli_tree(_get_parser())


def build_agentic_capsule() -> str:
    commands = [
        "list memories: ./bin/memory list --type feedback --format json",
        "show one memory: ./bin/memory show feedback-run-it-dont-just-read-it",
        "search all stores: ./bin/memory search worktree --all-stores --format json",
        "validate: ./bin/memory validate --format table",
        "validate + repair: ./bin/memory validate --fix --format table",
        "store roles: ./bin/memory stores --format table",
        "consolidate preview: ./bin/memory consolidate --dry-run",
        "export preview: ./bin/memory export --slug SLUG --output bundle.yaml --dry-run",
        "import: ./bin/memory import bundle.yaml --reindex --dry-run",
        "backup status: ./bin/memory backup --status",
    ]
    notes_body = "\n".join(
        [
            "- Offline: reads ~/.claude/projects/<slug>/memory/*.md and MEMORY.md; no credentials.",
            "- Default store is the one whose decoded repo path contains the cwd.",
            "- `validate` exits 0 clean, 1 warn/info only, 2 on any error finding.",
            "- `validate` skips stale-superseded-pr (calls GitHub) unless named via --check.",
            "- `[[slug]]` links compare with '-' and '_' folded, so either filename style resolves.",
            "- `export` refuses on any block-severity redaction; warn needs --allow-warn.",
            "- Archive and backup default under <data-home>/memory/ (core.paths.output_dir).",
        ]
    )
    return _build_capsule(
        "memory",
        "Claude auto-memory: list, show, search, validate, consolidate, export/import, backup",
        commands,
        [("Notes", notes_body)] + _tree_and_flow_sections(_cli_tree(), None),
    )


def build_domain_map() -> str:
    return _core_build_domain_map(
        "Top-Level\n"
        "- bin/memory — CLI wrapper (routed through _router.py)\n"
        "- memory/cli.py — CLIApp wiring; one subcommand per memory/commands/*.py\n"
        "- memory/parser.py — frontmatter dialects, Why/How split, wikilinks, anchors\n"
        "- memory/discovery.py — store discovery, slug decoding, canonical election\n"
        "- memory/index.py — MEMORY.md parse and atomic edits\n"
        "- memory/validation.py — check registry and --fix repairs\n"
        "- memory/consolidate.py, graduate.py — cross-store moves (archive, never delete)\n"
        "- memory/bundle.py, redaction.py — export/import bundles and secret scanning\n"
        "- memory/backup.py — local-only git backup",
        _cli_tree(),
        None,
    )


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
