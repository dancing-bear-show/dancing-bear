"""Common helpers for building agentic capsules across assistants."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

# argparse is optional at import time; type checking only.
try:  # pragma: no cover - best effort typing
    from argparse import ArgumentParser  # type: ignore
except Exception:  # pragma: no cover
    ArgumentParser = object  # type: ignore


def read_text(path: Path) -> str:
    """Return UTF-8 text for `path`, or empty string if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def section(title: str, body: str) -> str:
    """Render a simple '== title ==' section if body has non-whitespace content."""
    text = (body or "").strip()
    if not text:
        return ""
    return f"== {title} ==\n{text}\n"


def build_capsule(
    app_id: str,
    purpose: str,
    commands: Iterable[str],
    sections: Iterable[Tuple[str, str]],
) -> str:
    """Render a standard agentic capsule given metadata and sections."""
    out: List[str] = []
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


def _get_subparsers_action(parser: ArgumentParser) -> Optional[object]:
    for act in getattr(parser, "_actions", []):
        if act.__class__.__name__.endswith("SubParsersAction"):
            return act
    return None


def _child_choices(parser: ArgumentParser) -> List[str]:
    act = _get_subparsers_action(parser)
    if not act:
        return []
    choices = getattr(act, "choices", {}) or {}
    return sorted(choices.keys())


def build_cli_tree(parser: Optional[ArgumentParser], depth: int = 2) -> str:
    """Return a compact CLI tree string for the given parser."""
    if parser is None:
        return ""
    root_act = _get_subparsers_action(parser)
    if not root_act:
        return ""
    lines: List[str] = []
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


def cli_path_exists(parser: Optional[ArgumentParser], path: Sequence[str]) -> bool:
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


def list_subcommands(parser: Optional[ArgumentParser]) -> List[str]:
    """Return the top-level subcommands for a parser."""
    if parser is None:
        return []
    act = _get_subparsers_action(parser)
    if not act:
        return []
    return sorted(getattr(act, "choices", {}).keys())
