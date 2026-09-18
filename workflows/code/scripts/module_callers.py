"""Find every file that imports a target module, resolving imports via AST.

Answers "who imports this module?" for an ARBITRARY target — unlike
``detect_facades.py``, whose caller map is keyed on modules that are already
pure facades (``if tgt in facades``) and therefore returns nothing for a module
being split.

A string grep cannot answer this question:

- **Relative imports are invisible.** ``from .text_utils import x`` inside
  ``src/calendars/importer/`` targets ``calendars.importer.text_utils`` and
  shares no substring with it.
- **Lazy imports hide below the top level.** An import nested in a function
  body is not in ``tree.body``; only ``ast.walk`` reaches it.
- **Dots are wildcards.** ``grep "import mail.foo"`` also matches
  ``import mailXfoo``. ``grep -F`` fixes that but keeps the first two gaps.

This is not hypothetical. ``workflows/code/facade-elimination.yaml`` records
that a grep-based caller count once labelled 7 facades "zero callers — safe to
delete outright"; every one had real callers, and deleting on that signal would
have broken the build in 7 places.

Usage:
    PYTHONPATH=src python3 module_callers.py --module mail.config_resolver
    PYTHONPATH=src python3 module_callers.py --module mail.foo --format json
    PYTHONPATH=src python3 module_callers.py --module mail.foo --roots src tests bin

Exit codes:
    0  scan completed and covered every file (callers may be zero — that is a
       real answer)
    1  bad arguments, or a root that does not exist
    2  scan completed but one or more files could not be read or parsed, so
       the caller list is INCOMPLETE. A stale import inside an unparseable
       file would be missed, and acting on a zero count here could delete a
       module that still has callers. The unreadable paths are listed on
       stderr, and in the "unscannable" key with --format json.

Prints one caller path per line, sorted, or a JSON object with --format json.
A file is reported once however many times it imports the target.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections.abc import Iterator

SKIP_DIRS = {
    ".git", ".venv", ".claude", "__pycache__", "node_modules", ".cache",
    "personal_assistants.egg-info", ".facade-work",
}


def iter_py(roots: list[str]) -> Iterator[str]:
    """Yield every .py file under *roots*, skipping vendored/build dirs."""
    for root in roots:
        if os.path.isfile(root):
            if root.endswith(".py"):
                yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def module_path(path: str, src_root: str = "src") -> str:
    """Dotted module path for a file, relative to *src_root*.

    ``src/mail/providers/__init__.py`` -> ``mail.providers`` (the PACKAGE, not
    a ``.__init__`` submodule: definitions in that file carry
    ``__module__ == "mail.providers"``, so the phantom submodule would bind a
    second module object).
    """
    rel = os.path.relpath(path, src_root) if path.startswith(src_root + os.sep) else path
    dotted = rel[:-3].replace(os.sep, ".") if rel.endswith(".py") else rel
    if dotted.endswith(".__init__"):
        dotted = dotted[: -len(".__init__")]
    return dotted


def resolve_relative(level: int, module: str | None, pkg: str) -> str:
    """Resolve a relative import to an absolute dotted path.

    Mirrors ``detect_facades._resolve_relative_import``: *level* is the dot
    count (1 = current package), *module* is the name after the dots (None for
    a bare ``from . import x``), *pkg* is the importing file's package.
    """
    base = pkg
    for _ in range(level - 1):
        base = base.rsplit(".", 1)[0] if "." in base else ""
    return f"{base}.{module}" if module else base


def _parse(path: str, unscannable: list[str] | None = None) -> ast.Module | None:
    """Parse a file, or None if it cannot be read or parsed.

    A failure is RECORDED in *unscannable*, never silently absorbed. One
    broken file must not abort the inventory for every other file, but it
    also must not read as "this file imports nothing": that would turn a
    skipped file into evidence of zero callers, which is the false-clean this
    script exists to prevent.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())
    except (OSError, SyntaxError, UnicodeError):
        if unscannable is not None:
            unscannable.append(path)
        return None


def _from_targets(node: ast.ImportFrom, pkg: str) -> set[str]:
    """Modules referenced by one ``from x import y`` node."""
    target = resolve_relative(node.level, node.module, pkg) if node.level else node.module
    if not target:
        return set()
    # `from pkg import submodule` binds a MODULE, not a symbol, so the real
    # target is pkg.submodule — matching how detect_facades handles
    # `from worker import queue as q`.
    return {target} | {f"{target}.{alias.name}" for alias in node.names}


def _targets_in(path: str, src_root: str,
                unscannable: list[str] | None = None) -> set[str]:
    """Every module this file imports, absolute, including lazy imports.

    Files that cannot be parsed are appended to *unscannable* by ``_parse``;
    the empty set returned for them means "unknown", not "none".
    """
    tree = _parse(path, unscannable)
    if tree is None:
        return set()

    mod = module_path(path, src_root)
    pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
    found: set[str] = set()

    # ast.walk, NOT tree.body: a lazy import inside a function body is a real
    # caller and a body-only walk undercounts it.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found |= _from_targets(node, pkg)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def callers_of(target: str, roots: list[str],
               src_root: str = "src") -> tuple[list[str], list[str]]:
    """Files under *roots* that import *target*, resolved via AST.

    Returns ``(callers, unscannable)``. A non-empty *unscannable* makes the
    caller list incomplete — the second element is not advisory, and the CLI
    exits non-zero on it.
    """
    unscannable: list[str] = []
    callers = sorted(
        path for path in iter_py(roots)
        if target in _targets_in(path, src_root, unscannable)
    )
    return callers, sorted(unscannable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--module", required=True, help="dotted module path to find callers of")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["src", "tests", "bin"],
        help="directories to search (default: src tests bin)",
    )
    parser.add_argument("--src-root", default="src", help="package root for dotted paths")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    if not args.module.strip():
        print("error: --module requires a dotted module name", file=sys.stderr)
        return 1

    missing = [r for r in args.roots if not os.path.exists(r)]
    if missing:
        # Fail loudly: a mistyped root would silently report zero callers,
        # which is the exact false-clean this script exists to prevent.
        print(f"error: root(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    found, unscannable = callers_of(args.module, args.roots, args.src_root)

    if args.format == "json":
        json.dump({"module": args.module, "callers": found, "count": len(found),
                   "unscannable": unscannable, "complete": not unscannable},
                  sys.stdout, indent=1)
        print()
    else:
        for path in found:
            print(path)

    if unscannable:
        print(
            f"error: {len(unscannable)} file(s) could not be read or parsed; "
            "the caller list is INCOMPLETE and must not be treated as a zero "
            "count:",
            file=sys.stderr,
        )
        for path in unscannable:
            print(f"  {path}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
