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
- **Importing a descendant imports its ancestors.** ``import pkg.target.child``
  executes ``pkg/target/__init__.py``, so that file is a live caller of
  ``pkg.target`` even though the string never appears on its own.

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
    2  scan completed but one or more files could not be read or parsed, or
       a directory could not be listed, so the caller list is INCOMPLETE. A
       stale import inside an unreadable file or subtree would be missed, and
       acting on a zero count here could delete a module that still has
       callers. The affected paths are listed on stderr, and in the
       "unscannable" key with --format json.

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


def _walk_py(root: str, unscannable: list[str] | None) -> Iterator[str]:
    """Yield .py files under one directory, recording unlistable directories.

    ``os.walk`` defaults to ``onerror=None``, which drops an unreadable
    directory without a word — its files never reach ``_parse``, so a
    file-level error list stays empty and the scan reports complete while a
    whole subtree went unread.
    """
    def _on_error(err: OSError) -> None:
        if unscannable is not None:
            unscannable.append(getattr(err, "filename", None) or str(err))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def iter_py(roots: list[str], unscannable: list[str] | None = None) -> Iterator[str]:
    """Yield every .py file under *roots*, skipping vendored/build dirs.

    Directories that cannot be listed are appended to *unscannable*.
    """
    for root in roots:
        if os.path.isfile(root):
            if root.endswith(".py"):
                yield root
        else:
            yield from _walk_py(root, unscannable)


def module_path(path: str, src_root: str = "src") -> str:
    """Dotted module path for a file, relative to *src_root*.

    ``src/mail/providers/__init__.py`` -> ``mail.providers`` (the PACKAGE, not
    a ``.__init__`` submodule: definitions in that file carry
    ``__module__ == "mail.providers"``, so the phantom submodule would bind a
    second module object).

    *path* and *src_root* are compared as resolved absolute paths, so an
    absolute ``--roots`` works with the default relative ``--src-root``. A
    textual ``startswith`` check missed that case: ``os.walk`` over an
    absolute root yields absolute filenames, which never start with ``src/``,
    so the whole filesystem path became the dotted name
    (``.var.folders.…tmpXXXX.src.pkg.mod``). Every relative import inside such
    a file then resolved against a nonsense package and its callers vanished
    — while the scan still exited 0 and reported complete.
    """
    # realpath, not abspath: abspath does not resolve symlinks, so a checkout
    # reached through one (/var -> /private/var on macOS, or a symlinked
    # worktree) compares unequal and falls through to the broken branch.
    abs_path = os.path.realpath(path)
    abs_root = os.path.realpath(src_root)
    if abs_path == abs_root or abs_path.startswith(abs_root + os.sep):
        rel = os.path.relpath(abs_path, abs_root)
    else:
        rel = path
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


def _with_ancestors(dotted: str) -> set[str]:
    """*dotted* plus every ancestor package it necessarily imports.

    ``import pkg.target.child`` executes ``pkg/__init__.py`` and
    ``pkg/target/__init__.py`` before binding the leaf, so the importing file
    is a live caller of all three. Recording only the leaf let a split or
    delete of ``pkg.target`` proceed while that caller still depended on it.
    """
    parts = dotted.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _is_module(dotted: str, src_root: str) -> bool:
    """Whether *dotted* names a module or package file under *src_root*.

    ``from pkg import name`` binds a submodule only when ``pkg/name.py`` or
    ``pkg/name/__init__.py`` exists; otherwise *name* is a class, function or
    value re-exported by ``pkg/__init__.py``. Recording ``pkg.name`` in the
    second case invents a module and reports a false caller of it, which the
    sweep then demands be rewritten.
    """
    rel = os.path.join(*dotted.split("."))
    base = os.path.join(src_root, rel)
    return os.path.isfile(base + ".py") or os.path.isfile(
        os.path.join(base, "__init__.py")
    )


def _from_targets(node: ast.ImportFrom, pkg: str, src_root: str = "src") -> set[str]:
    """Modules referenced by one ``from x import y`` node."""
    target = resolve_relative(node.level, node.module, pkg) if node.level else node.module
    if not target:
        return set()
    # `from pkg import submodule` binds a MODULE, so the real target is
    # pkg.submodule — but ONLY when that submodule exists on disk. An alias
    # that resolves to no file is a symbol, not a module; adding it anyway
    # reported callers of modules that never existed.
    found = _with_ancestors(target)
    for alias in node.names:
        candidate = f"{target}.{alias.name}"
        if _is_module(candidate, src_root):
            found |= _with_ancestors(candidate)
    return found


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
    # An __init__.py IS its package, so a relative import inside it resolves
    # against the package itself. Stripping the last segment (correct for a
    # plain module) would make `from .base import X` in mail/providers/
    # resolve to mail.base instead of mail.providers.base, missing every
    # caller that imports through a package initializer.
    if os.path.basename(path) == "__init__.py":
        pkg = mod
    else:
        pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
    found: set[str] = set()

    # ast.walk, NOT tree.body: a lazy import inside a function body is a real
    # caller and a body-only walk undercounts it.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found |= _from_targets(node, pkg, src_root)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found |= _with_ancestors(alias.name)
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
        path for path in iter_py(roots, unscannable)
        if target in _targets_in(path, src_root, unscannable)
    )
    return callers, sorted(set(unscannable))


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

    if not os.path.isdir(args.src_root):
        # --src-root drives every relative-import resolution AND the
        # submodule-vs-symbol check. A mistyped value makes module_path()
        # fall back to the raw path, so relative callers disappear while the
        # scan still exits 0 and calls itself complete — the same false clean
        # a mistyped --roots would produce, which is already rejected above.
        print(
            f"error: --src-root not found or not a directory: {args.src_root}",
            file=sys.stderr,
        )
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
