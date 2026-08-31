"""Unadopted-abstraction detector.

Finds shared abstractions that EXIST but were never adopted. This is the defect
class that clone detection structurally cannot see: qlty matches token
sequences, so a helper in ``core/`` that nobody calls is invisible to it, and so
is the hand-rolled code that should have called it.

Every genuine finding of the 2026-08-28 abstraction audit was this shape, and
all three were found by hand rather than by any tool:

- ``OutputWriter.print_dry_run`` -- 1 occurrence repo-wide, its own definition,
  against ~31 hand-rolled ``if dry_run:`` branches.
- ``core.pipeline.BaseProducer`` -- 65 subclasses, yet 21 mail producers
  implemented the ``Producer`` protocol directly and re-coded its error gate.
- ``tests.fixtures.make_mock_envelope`` -- 3 real consumers against 8 files
  hand-rolling ``MagicMock()`` + ``.ok.return_value``.

Two modes:

  python3 detect_unadopted.py python    # core/ symbols vs their call sites
  python3 detect_unadopted.py workflows # shared/ fragments vs `include:` users

Output is JSON on stdout. Findings are RANKED SUSPICIONS, not defects: a symbol
with few call sites may be new, deliberately narrow, or a public API for
external callers. Verify each by reading before acting.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import defaultdict

SRC = "src"
CORE = os.path.join(SRC, "core")
TESTS = "tests"
WORKFLOWS = "workflows"
SHARED = os.path.join(WORKFLOWS, "shared")

SKIP_WALK_DIRS = {
    ".git", ".venv", ".claude", ".claire", "__pycache__", "node_modules",
    ".cache", "out", "_out", "backups", "personal_assistants.egg-info",
}

#: A symbol defined in core/ but called this few times outside its own module
#: is a candidate. Tuned to surface print_dry_run (1) without drowning in
#: legitimately-narrow helpers.
LOW_ADOPTION = 3

#: Dunder and private names are excluded: they are not the shared surface.
PUBLIC = re.compile(r"^[a-z][a-z0-9_]*$|^[A-Z][A-Za-z0-9]*$")


def iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def parse_py(path: str) -> ast.Module | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read(), filename=path)
    # A file that is not valid UTF-8, or carries a bad encoding declaration,
    # would otherwise abort the whole scan -- neither raises OSError.
    # ValueError covers UnicodeDecodeError (its subclass) and the null-byte
    # ValueError that ast.parse raises. detect_facades.py treats decode
    # failures as non-fatal the same way.
    except (OSError, SyntaxError, ValueError):
        return None


def _is_public(name: str) -> bool:
    return bool(PUBLIC.match(name)) and not name.startswith("_")


def _class_symbols(node: ast.ClassDef) -> list[tuple[str, str, int]]:
    """The class itself plus its public methods, as ``Class.method``."""
    out = [(node.name, "class", node.lineno)]
    for sub in node.body:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(sub.name):
            out.append((f"{node.name}.{sub.name}", "method", sub.lineno))
    return out


def public_symbols(path: str) -> list[tuple[str, str, int]]:
    """Return (name, kind, lineno) for public defs/classes in a module.

    Methods are included as ``Class.method`` because the adoption question
    applies to them too -- print_dry_run is a method, not a free function.
    """
    tree = parse_py(path)
    if tree is None:
        return []
    out: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
            out.append((node.name, "function", node.lineno))
        elif isinstance(node, ast.ClassDef) and _is_public(node.name):
            out.extend(_class_symbols(node))
    return out


#: path -> contents. Every symbol is counted against the same corpus, and
#: scan_python asks twice per symbol, so without this the tree is re-read
#: hundreds of times: 28.7s down to well under a second on this repo.
_FILE_CACHE: dict[str, str] = {}


_ABSPATH_CACHE: dict[str, str] = {}


def _abspath(path: str) -> str:
    """os.path.abspath calls getcwd() every time; the corpus is fixed."""
    if path not in _ABSPATH_CACHE:
        _ABSPATH_CACHE[path] = os.path.abspath(path)
    return _ABSPATH_CACHE[path]


def _read_cached(path: str) -> str:
    if path not in _FILE_CACHE:
        try:
            with open(path, encoding="utf-8") as fh:
                _FILE_CACHE[path] = fh.read()
        except (OSError, UnicodeDecodeError):
            # An unreadable or non-UTF-8 file contributes no usages rather than
            # aborting the scan; cached as "" so it is not retried per symbol.
            _FILE_CACHE[path] = ""
    return _FILE_CACHE[path]


def count_usages(name: str, files: list[str], defining_file: str) -> int:
    """Count textual occurrences of a symbol outside the module defining it.

    Deliberately textual rather than AST-resolved: a method is reached as
    ``self._writer.print_dry_run(...)``, where no import or attribute chain
    ties it back to its class. An AST resolver would report zero for exactly
    the cases this is meant to catch. The cost is that a name shared with an
    unrelated symbol over-counts -- which errs toward silence, not noise.
    """
    bare = name.split(".")[-1]
    pattern = re.compile(rf"\b{re.escape(bare)}\b")
    skip = _abspath(defining_file) if defining_file else None
    total = 0
    for path in files:
        if skip is not None and _abspath(path) == skip:
            continue
        text = _read_cached(path)
        # A substring test is ~5x cheaper than a regex scan and cannot miss a
        # word-boundary match, since any \bname\b also contains `name`. The
        # regex still runs on the few files that pass, so counts are unchanged.
        if bare in text:
            total += len(pattern.findall(text))
    return total


def _verdict(external: int, internal: int, defs: int) -> str:
    """Classify a symbol by where, if anywhere, it is actually used."""
    if external:
        return "low-adoption"
    return "internal-only" if internal > defs else "dead-or-unadopted"


def scan_python() -> list[dict]:
    if not os.path.isdir(CORE):
        return []
    call_sites = [p for p in iter_py(SRC)] + [p for p in iter_py(TESTS)]
    findings: list[dict] = []
    for core_file in iter_py(CORE):
        for name, kind, lineno in public_symbols(core_file):
            external = count_usages(name, call_sites, core_file)
            if external > LOW_ADOPTION:
                continue
            # Intra-module use means the symbol is a working internal helper
            # that merely happens to be public -- adopted, not dead. Reporting
            # only the external count made four such helpers look unused.
            internal = count_usages(name, [core_file], defining_file="")
            # The definition itself is one occurrence. Do NOT also discount an
            # __all__ entry: a class with one intra-module use and no __all__
            # then scored internal == defs and was misreported as dead. Counting
            # an __all__ mention as a real internal usage errs toward
            # "internal-only", which is the safe direction for a heuristic.
            defs = 1
            findings.append(
                {
                    "kind": "unadopted-symbol",
                    "symbol": name,
                    "symbol_kind": kind,
                    "file": core_file,
                    "line": lineno,
                    "usages_outside_defining_module": external,
                    "usages_inside_defining_module": max(0, internal - defs),
                    "verdict": _verdict(external, internal, defs),
                }
            )
    order = {"dead-or-unadopted": 0, "low-adoption": 1, "internal-only": 2}
    findings.sort(
        key=lambda f: (
            order[f["verdict"]],
            f["usages_outside_defining_module"],
            f["file"],
            f["symbol"],
        )
    )
    return findings


def iter_yaml(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
        for fn in sorted(filenames):
            if fn.endswith((".yaml", ".yml")):
                yield os.path.join(dirpath, fn)


def scan_workflows() -> list[dict]:
    """Shared workflow fragments that NO workflow includes.

    Zero includers only, unlike the Python scan's LOW_ADOPTION threshold. A
    fragment with even one includer is doing its job -- fragments are composed
    deliberately per workflow shape, so "used twice instead of five times" is
    not evidence of anything, whereas "never used" is.

    The engine supports `include:` (src/workflow/include.py), and
    workflows/shared/ holds the fragments. A fragment nobody includes is the
    same defect as an uncalled core helper: the abstraction exists, the callers
    hand-roll instead.
    """
    if not os.path.isdir(SHARED):
        return []

    # Match on the fragment's PATH, not its basename. `include:` entries name
    # `path: workflows/shared/<frag>.yaml`, and a bare stem also matches the
    # fragment's own `name:` field -- which made every fragment look
    # self-referencing and, worse, made genuinely-used ones look unused.
    consumers = [p for p in iter_yaml(WORKFLOWS) if not p.startswith(SHARED + os.sep)]

    # Skills invoke workflows too, so a fragment used only from a SKILL.md is
    # adopted, not dead.
    extra_roots = [".claude/skills", ".claude/commands"]
    for root in extra_roots:
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
                consumers += [
                    os.path.join(dirpath, fn)
                    for fn in filenames
                    if fn.endswith((".md", ".yaml", ".yml"))
                ]

    # _read_cached rather than a second open(): it already handles unreadable
    # and non-UTF-8 files, and shares the cache with the python scan.
    texts = {path: _read_cached(path) for path in consumers}

    findings: list[dict] = []
    for frag in iter_yaml(SHARED):
        stem = os.path.splitext(os.path.basename(frag))[0]
        needle = frag.replace(os.sep, "/")
        includers = [p for p, text in texts.items() if needle in text]
        if len(includers) == 0:
            findings.append(
                {
                    "kind": "unadopted-fragment",
                    "fragment": stem,
                    "file": frag,
                    "included_by_count": 0,
                    "included_by": [],
                }
            )
    findings.sort(key=lambda f: f["fragment"])
    return findings


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "python"
    if mode == "python":
        findings = scan_python()
    elif mode == "workflows":
        findings = scan_workflows()
    elif mode == "all":
        findings = scan_python() + scan_workflows()
    else:
        print(f"unknown mode: {mode} (want python|workflows|all)", file=sys.stderr)
        return 2

    by_kind: dict[str, int] = defaultdict(int)
    for f in findings:
        by_kind[f["kind"]] += 1

    json.dump(
        {
            "mode": mode,
            "low_adoption_threshold": LOW_ADOPTION,
            "counts": dict(by_kind),
            "note": (
                "Ranked suspicions, not defects. A low count may mean new, "
                "deliberately narrow, or an external public API. Read before acting."
            ),
            "findings": findings,
        },
        sys.stdout,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
