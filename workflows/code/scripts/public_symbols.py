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


def _public_defs(tree: ast.Module) -> set[str]:
    """Public top-level class/function names in *tree*, DEDUPLICATED.

    A set, not a list: ``@overload`` declares the same name several times at
    module level (``src/mail/config_resolver.py`` declares ``expand_path``
    three times plus its implementation), and a per-node list would report
    that name four times while any runtime view sees it once — an unchanged
    module then looks like it lost exports.
    """
    return {
        node.name
        for node in tree.body
        if isinstance(node, _DEF_KINDS) and not node.name.startswith("_")
    }


def from_source(path: str) -> list[str]:
    """Public top-level classes/functions defined in the file at *path*."""
    with open(path, encoding="utf-8") as fh:
        return sorted(_public_defs(ast.parse(fh.read())))


def from_module(dotted: str) -> list[str]:
    """Public classes/functions defined by the module named *dotted*.

    Derived from the module's OWN SOURCE, then confirmed against the imported
    module — not inferred from runtime metadata. Runtime attributes cannot
    answer "what did this module define" reliably, and two cases prove it:

    - **Decorators without ``functools.wraps``.** ``@deco def public_thing()``
      binds a wrapper whose ``__name__`` is ``wrapper``, so a
      ``__name__``-matching predicate drops the name entirely. Verified: a
      no-wraps module reported ``public_thing`` from source and nothing from
      a metadata-based runtime pass.
    - **Aliases of local definitions.** ``class Foo`` plus ``PublicAlias =
      Foo`` binds two names to one object whose ``__module__`` matches both,
      so an attribute-only pass invents a name the source never declares.

    Parsing the source settles both, because the question is about
    definitions rather than bindings. The import still happens, for two
    reasons: an unimportable module must fail loudly (a missing export is
    indistinguishable from a broken module otherwise), and a name the source
    defines but the module does not expose at runtime is a real defect worth
    surfacing.
    """
    mod = importlib.import_module(dotted)

    source_file = getattr(mod, "__file__", None)
    if not source_file or not source_file.endswith(".py"):
        # Namespace package, C extension, or frozen module: no source to
        # parse. Fall back to runtime attributes, accepting the decorator and
        # alias caveats above rather than silently returning nothing.
        return sorted(
            name
            for name, value in vars(mod).items()
            if not name.startswith("_")
            and not isinstance(value, types.ModuleType)
            and (isinstance(value, type) or callable(value))
            and getattr(value, "__module__", None) == dotted
        )

    with open(source_file, encoding="utf-8") as fh:
        defined = _public_defs(ast.parse(fh.read()))

    # A defined name absent at runtime is a genuine finding, not noise to
    # hide: report only what the module actually exposes, so the caller's
    # diff shows the gap.
    return sorted(name for name in defined if hasattr(mod, name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="path to a .py file to parse")
    group.add_argument("--module", help="importable dotted module path")
    args = parser.parse_args(argv)

    # Select on `is not None`, never truthiness. With `if args.source`, an
    # empty --source silently falls through to from_module(None) and raises an
    # uncaught TypeError; an empty --module reaches importlib and raises
    # ValueError, which the ImportError handler does not catch. Both leaked a
    # traceback instead of the documented exit-1 contract.
    use_source = args.source is not None

    if use_source and not args.source.strip():
        print("error: --source requires a path", file=sys.stderr)
        return 1
    if not use_source and not (args.module or "").strip():
        print("error: --module requires a dotted module name", file=sys.stderr)
        return 1

    try:
        names = from_source(args.source) if use_source else from_module(args.module)
    # UnicodeError covers UnicodeDecodeError from a non-UTF-8 source file:
    # without it the CLI emits a traceback instead of the documented exit-1
    # contract, and a caller parsing stderr cannot tell the two apart.
    except (OSError, SyntaxError, UnicodeError) as exc:
        print(f"error: cannot read or parse source: {exc}", file=sys.stderr)
        return 1
    # ValueError and TypeError join ImportError because importlib raises them
    # for malformed names rather than ImportError: an empty segment raises
    # ValueError, and a RELATIVE name (".bad") raises TypeError complaining
    # that the 'package' argument is required. Verified both.
    except (ImportError, ValueError, TypeError) as exc:
        print(f"error: cannot import module: {exc}", file=sys.stderr)
        return 1

    for name in names:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
