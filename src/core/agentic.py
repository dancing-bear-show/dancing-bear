"""Common helpers for building agentic capsules across assistants."""
from __future__ import annotations

from functools import lru_cache
from typing import Callable, Iterable, Sequence

# argparse is optional at import time; type checking only.
try:  # pragma: no cover - best effort typing
    from argparse import ArgumentParser
except Exception:  # pragma: no cover
    ArgumentParser = object  # type: ignore


def section(title: str, body: str | None) -> str:
    """Render a simple '== title ==' section if body has non-whitespace content."""
    text = (body or "").strip()
    if not text:
        return ""
    return f"== {title} ==\n{text}\n"


def build_capsule(
    app_id: str,
    purpose: str,
    commands: Iterable[str],
    sections: Iterable[tuple[str, str]],
) -> str:
    """Render a standard agentic capsule given metadata and sections."""
    out: list[str] = []
    out.append(f"agentic: {app_id}")
    out.append(f"purpose: {purpose}")
    out.append("commands:")
    for cmd in commands:
        out.append(f"  - {cmd}")
    out.append("")
    for title, body in sections:
        sec = section(title, body)
        if sec:
            out.append(sec)
    return "\n".join([s for s in out if s.strip()])


def tree_and_flow_sections(
    cli_tree: str | None,
    flow_map: str | None,
) -> list[tuple[str, str]]:
    """Return the standard (title, body) pairs, dropping empty ones.

    Every domain capsule appends a "CLI Tree" section and a "Flow Map"
    section, each guarded on being non-empty. Centralizing the pair keeps
    the section titles and the skip-if-empty rule in one place.

    Bodies are typed as optional because the callers' _cli_tree()/_flow_map()
    are best-effort: build_cli_tree returns "" when the CLI module cannot be
    imported, and a None slipping through must not raise here. Whitespace-only
    bodies survive this filter and are stripped later by section().
    """
    pairs = (("CLI Tree", cli_tree), ("Flow Map", flow_map))
    return [(title, body) for title, body in pairs if body]


def build_domain_map(
    top_level: str | None,
    cli_tree: str | None,
    flow_map: str | None,
) -> str:
    """Render a domain map: a Top-Level blurb plus the standard sections.

    Section titles and the skip-if-empty rule come from
    tree_and_flow_sections, and each body is rendered by section(), so the
    section handling matches build_capsule's. The Top-Level blurb is held to
    the same standard: blank-or-whitespace is dropped rather than emitting a
    leading empty line.
    """
    out: list[str] = [top_level or ""]
    out.extend(
        section(title, body)
        for title, body in tree_and_flow_sections(cli_tree, flow_map)
    )
    return "\n".join([s for s in out if s.strip()])


def _get_subparsers_action(parser: ArgumentParser) -> object | None:
    for act in getattr(parser, "_actions", []):
        if act.__class__.__name__.endswith("SubParsersAction"):
            return act
    return None


def _child_choices(parser: ArgumentParser) -> list[str]:
    act = _get_subparsers_action(parser)
    if not act:
        return []
    choices = getattr(act, "choices", {}) or {}
    return sorted(choices.keys())


def build_cli_tree(parser: ArgumentParser | None, depth: int = 2) -> str:
    """Return a compact CLI tree string for the given parser."""
    if parser is None:
        return ""
    root_act = _get_subparsers_action(parser)
    if not root_act:
        return ""
    lines: list[str] = []
    for name, subp in sorted(getattr(root_act, "choices", {}).items()):
        if depth <= 1:
            lines.append(f"- {name}")
            continue
        children = _child_choices(subp)
        if children:
            lines.append(f"- {name}: {', '.join(children)}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def cli_path_exists(parser: ArgumentParser | None, path: Sequence[str]) -> bool:
    """Return True if the parser exposes a nested path of subcommands."""
    if parser is None:
        return False
    cur = parser
    for name in path:
        act = _get_subparsers_action(cur)
        if not act:
            return False
        choices = getattr(act, "choices", {}) or {}
        cur = choices.get(name)
        if cur is None:
            return False
    return True


def list_subcommands(parser: ArgumentParser | None) -> list[str]:
    """Return the top-level subcommands for a parser."""
    if parser is None:
        return []
    act = _get_subparsers_action(parser)
    if not act:
        return []
    return sorted(getattr(act, "choices", {}).keys())


def cached_parser_loader(load_parser: Callable[[], ArgumentParser]) -> Callable[[], ArgumentParser | None]:
    """Wrap a parser-building callable with the standard try/except/cache shape.

    `load_parser` does the module-specific import and returns a built parser,
    raising if the CLI module can't be imported. The returned callable caches
    its result for the process lifetime (mirroring the previous per-module
    `@lru_cache(maxsize=1)` pattern) and returns None on any failure.
    """

    @lru_cache(maxsize=1)
    def _get_parser() -> ArgumentParser | None:
        try:
            return load_parser()
        except Exception:  # nosec B110 - best-effort; CLI module may be unavailable/broken, callers treat None as "no CLI tree"
            return None

    return _get_parser
