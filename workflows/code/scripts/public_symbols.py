"""Extract a module's public top-level symbols, from source or at runtime.

Used by workflows/code/qlty-complexity-sweep.yaml's export-parity check, which
compares a file's pre-refactor symbols against its post-refactor ones. The two
sides MUST apply the same predicate or the comparison produces noise in both
directions:

- ``grep "^class \\|^def "`` includes private names that a ``dir()`` filter
  excludes, so every ordinary private helper reads as a missing export -- and
  it silently misses ``async def``, so public coroutines are never checked.
- a bare ``dir(module)`` lists every public name the module *imported*, which
  masks a genuinely missing definition behind an unrelated import.

Both modes here return exactly: public (no leading underscore) top-level
classes and functions, including async functions, that the module itself
defines.

Usage:
    # from a source file (e.g. a `git show HEAD:path` blob)
    python3 public_symbols.py --source /tmp/head-version.py

    # from the imported module, own definitions only
    PYTHONPATH=src python3 public_symbols.py --module qlty.strategies

Prints one symbol per line, sorted. Exit 1 on unreadable/unparseable input or
an unimportable module, so a caller cannot mistake failure for "no symbols".
"""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
import types

_DEF_KINDS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def from_source(path: str) -> list[str]:
    """Public top-level classes/functions defined in the file at *path*."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return sorted(
        node.name
        for node in tree.body
        if isinstance(node, _DEF_KINDS) and not node.name.startswith("_")
    )


def from_module(dotted: str) -> list[str]:
    """Public classes/functions *defined by* the module named *dotted*.

    Mirrors :func:`from_source`, which reports only top-level classes and
    functions, so the two can be compared directly. Four exclusions make that
    equivalence hold:

    - ``__module__ != dotted`` drops names imported from elsewhere and merely
      re-exported, which a bare ``dir()`` would count as the module's own.
    - module objects are dropped explicitly. ``import json.decoder`` binds a
      submodule as an attribute of ``json``, and a module has no
      ``__module__``, so an attribute-defaulting check misattributes it.
    - non-callable, non-class values (constants) are dropped, because
      :func:`from_source` does not report assignments either.
    - an ALIAS of a local definition is dropped: ``class Foo: ...`` followed by
      ``PublicAlias = Foo`` binds two names to one object, and the object's
      ``__module__`` matches for both, so an attribute-only check reports a
      name :func:`from_source` never sees. Requiring ``value.__name__`` to
      equal the binding name keeps the two sides symmetric. (A decorated
      function still passes: ``functools.wraps`` copies ``__name__``, and an
      undecorated rename is genuinely an alias.)
    """
    mod = importlib.import_module(dotted)
    return sorted(
        name
        for name, value in vars(mod).items()
        if not name.startswith("_")
        and not isinstance(value, types.ModuleType)
        and (isinstance(value, type) or callable(value))
        and getattr(value, "__module__", None) == dotted
        and getattr(value, "__name__", name) == name
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="path to a .py file to parse")
    group.add_argument("--module", help="importable dotted module path")
    args = parser.parse_args(argv)

    try:
        names = from_source(args.source) if args.source else from_module(args.module)
    except (OSError, SyntaxError) as exc:
        print(f"error: cannot read or parse source: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"error: cannot import module: {exc}", file=sys.stderr)
        return 1

    for name in names:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
