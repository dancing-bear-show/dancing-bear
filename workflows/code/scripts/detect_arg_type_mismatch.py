"""Argument-type mismatch detector — static heuristic for S5655 candidates.

Finds call sites where a literal constant (None, a str, an int, …) is passed
positionally to a parameter whose annotation clearly excludes that type.

WHY THIS EXISTS
---------------
qlty's ``radarlint-python:python:S5655`` ("Change this argument; Function X
expects a different type") is nondeterministically capped per run.  Measured on
this repo: a single run finds 0–4 findings, different ones each time; a 28-run
union still found only 2; a static AST pass found 14 — a strict superset.  That
gap is why a repo-internal detector is worth having.

KNOWN LIMITATIONS
-----------------
- Only *literal* constants are inspected (``None``, string/int/float literals).
  Variables and expressions are not resolved.
- Only calls whose callee name was explicitly imported via ``from X import Y``
  are resolved.  Attribute calls (``obj.method()``) are genuinely skipped: the
  receiver carries the type, and matching on the bare attribute name made
  ``a.foo()``, ``b.foo()`` and ``self.foo()`` indistinguishable.
- Only positional arguments are inspected.  Keyword arguments, ``*args`` /
  ``**kwargs``, and default values are not, and a signature rewritten by a
  decorator is read as written.  ``@overload`` resolves to whichever ``def``
  is parsed last.
- The signature table is keyed by ``(module_stem, funcname)``, which cannot
  distinguish sibling classes in one file -- ``consumers.consume`` is defined
  37 times in a single module.  Ambiguous keys are DROPPED, not guessed (122 on
  this repo); ``stats.signatures_ambiguous_dropped`` reports how many, so the
  blind spot is visible rather than silent.
- Nested and inner functions are not collected: only module-level ``def`` and
  class bodies are walked.
- The resolver is heuristic, not a type-checker.  Verify each finding before
  acting on it.
- Annotations are compared as PARSED syntax, not resolved types.  The None
  check inspects top-level union members, so ``dict[str, Any]`` is correctly
  None-hostile (a substring test accepted it -- 270 parameters on this repo,
  the single most common annotation).  What remains unresolved is anything
  requiring name resolution: a bare ``TypeVar`` (``T``) or an alias such as
  ``JsonValue`` is reported even when it permits None, because the name alone
  does not say so.

CONFIDENCE
----------
Findings are CANDIDATES, not proven defects.  The note field in the JSON output
says so explicitly.  Follow ``detect_unadopted.py``'s precedent: "Read before
acting."

USAGE
-----
Run from the repo root (the script discovers ``src/`` and ``tests/`` relative
to ``cwd``):

    python3 workflows/code/scripts/detect_arg_type_mismatch.py

Optional env vars:
    SRC_ROOT   — directory to scan for signatures (default: ``src``)
    TEST_ROOT  — directory to scan for call sites (default: ``tests``)
"""

from __future__ import annotations

import ast
import json
import os
import sys

SRC_ROOT = os.environ.get("SRC_ROOT", "src")
TEST_ROOT = os.environ.get("TEST_ROOT", "tests")

SKIP_WALK_DIRS = {
    ".git", ".venv", ".claude", "__pycache__", "node_modules",
    ".cache", "out", "_out", "backups", "personal_assistants.egg-info",
}

# ---------------------------------------------------------------------------
# Signature collection
# ---------------------------------------------------------------------------

#: ``(module_stem, funcname) -> (src_path, lineno, [(param_name, annotation)])``
Sigs = dict[tuple[str, str], tuple[str, int, list[tuple[str, str | None]]]]

#: Keys claimed by more than one definition. The table is keyed by
#: (module_stem, funcname), which cannot distinguish sibling classes in one
#: file -- `consumers.consume` is defined 37 times in a single module. Whichever
#: definition wins is arbitrary, so an ambiguous key is DROPPED rather than
#: guessed: a wrong signature yields confidently wrong findings, whereas a
#: missing one yields silence that `stats` reports.
_AMBIGUOUS: set[tuple[str, str]] = set()


def _iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _parse_py(path: str) -> ast.Module | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None  # nosec B112 - skip unreadable/bad-encoding files silently


def _has_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True if ``func`` carries a decorator spelled ``name``, bare or dotted."""
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == name:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == name:
            return True
    return False


def _has_classmethod_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return _has_decorator(func, "classmethod")


def _has_staticmethod_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True for @staticmethod, which takes NO receiver.

    Distinguishing this matters: a staticmethod's first parameter is a real
    one. Treating it as an instance method deletes that parameter and shifts
    every index after it -- the same index-shift bug the `cls` fix addressed,
    just reached by a different route. A single-parameter staticmethod
    collapses to zero parameters and becomes permanently invisible.
    """
    return _has_decorator(func, "staticmethod")


def _collect_params(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    is_method: bool,
    is_classmethod: bool,
) -> list[tuple[str, str | None]]:
    """Return [(param_name, annotation_str)] for the non-receiver parameters.

    ``self`` is always skipped for instance methods (is_method=True).
    ``cls`` is skipped only for classmethods (is_classmethod=True).  A plain
    function whose first parameter happens to be named ``cls`` must NOT be
    stripped — that shifts every subsequent positional index and produces false
    positives.  This is the key fix over the prototype, which stripped every
    parameter literally named ``self`` or ``cls`` regardless of context.
    """
    args = func.args.posonlyargs + func.args.args
    skip_indices: set[int] = set()

    if (is_method or is_classmethod) and args:
        # Receiver is always the first positional parameter.
        skip_indices.add(0)

    result: list[tuple[str, str | None]] = []
    for i, arg in enumerate(args):
        if i in skip_indices:
            continue
        ann = ast.unparse(arg.annotation) if arg.annotation else None
        result.append((arg.arg, ann))
    return result


def _collect_class_sigs(
    node: ast.ClassDef, path: str, mod: str, sigs: Sigs
) -> None:
    """Collect signatures for all methods in a class body into ``sigs``."""
    for member in node.body:
        if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_cm = _has_classmethod_decorator(member)
        is_sm = _has_staticmethod_decorator(member)
        # A staticmethod has no receiver at all, so it is neither.
        params = _collect_params(
            member,
            is_method=not is_cm and not is_sm,
            is_classmethod=is_cm,
        )
        key = (mod, member.name)
        if key in sigs:
            # Same (module, name) already claimed -- typically sibling classes
            # in one file (`consumers.consume` collides 37 ways). Keeping the
            # first is no more correct than keeping the last, so record the
            # ambiguity and drop the key entirely: a wrong signature produces
            # confidently wrong findings, while a missing one only produces
            # silence that `stats` now makes visible.
            _AMBIGUOUS.add(key)
            sigs.pop(key, None)
            continue
        sigs[key] = (path, member.lineno, params)


#: Files walked and files that failed to parse, per root. A detector that
#: reports zero because it scanned nothing is indistinguishable from one that
#: reports zero because the code is clean -- the exact false-clean this repo
#: has been bitten by before (see CLAUDE.md on qlty scanning zero files in a
#: worktree, and src/qlty/README.md F1). Counted so the caller can tell.
_STATS: dict[str, int] = {
    "src_files_scanned": 0,
    "src_files_unparsed": 0,
    "test_files_scanned": 0,
    "test_files_unparsed": 0,
    "signatures_collected": 0,
    "signatures_ambiguous_dropped": 0,
}


def _reset_stats() -> None:
    """Zero the scan counters so repeated in-process runs do not accumulate."""
    for key in _STATS:
        _STATS[key] = 0
    _AMBIGUOUS.clear()


def collect_signatures(src_root: str) -> Sigs:
    """Walk ``src_root`` and collect annotated function/method signatures."""
    _reset_stats()
    sigs: Sigs = {}
    for path in _iter_py(src_root):
        _STATS["src_files_scanned"] += 1
        tree = _parse_py(path)
        if tree is None:
            _STATS["src_files_unparsed"] += 1
            continue
        mod = os.path.splitext(os.path.basename(path))[0]
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _collect_params(node, is_method=False, is_classmethod=False)
                key = (mod, node.name)
                if key in sigs:
                    _AMBIGUOUS.add(key)
                    sigs.pop(key, None)
                    continue
                sigs[key] = (path, node.lineno, params)
            elif isinstance(node, ast.ClassDef):
                _collect_class_sigs(node, path, mod, sigs)
    # Drop every key an ambiguity was recorded for, including ones first seen
    # after the collision was noted.
    for key in _AMBIGUOUS:
        sigs.pop(key, None)
    _STATS["signatures_collected"] = len(sigs)
    _STATS["signatures_ambiguous_dropped"] = len(_AMBIGUOUS)
    return sigs


# ---------------------------------------------------------------------------
# Type-compatibility check
# ---------------------------------------------------------------------------

#: Annotation tokens that permit None.
_NONE_OK = {"None", "Optional", "Any", "object"}
#: Base types (before ``[``) that disallow a bare string literal.
_STR_HOSTILE_BASES = {"dict", "list", "int", "float", "bool"}
#: Base types that disallow a bare int/float literal.
_INT_HOSTILE_BASES = {"str", "dict", "list"}


def _top_level_union_members(ann: str) -> list[str]:
    """Split an annotation into its TOP-LEVEL union members.

    Parsed rather than substring-matched. `dict[str, Any]` contains "Any" as a
    substring, so a substring test accepted None for the single most common
    annotation in this repo -- 270 parameters, and the reason
    `_normalize_range(None)` against `ev: dict[str, Any]` went unreported while
    the string literal on the adjacent line was caught.

    Falls back to the whole string when the annotation will not parse, e.g. a
    forward reference already carrying quotes.
    """
    try:
        expr = ast.parse(ann, mode="eval").body
    except SyntaxError:
        return [ann]

    members: list[str] = []
    _walk_union(expr, members)
    return members


def _union_subscript_elements(node: ast.Subscript) -> list[ast.expr] | None:
    """Return the member expressions of ``Optional[X]``/``Union[A, B]``.

    None when the subscript is an ordinary generic such as ``dict[str, Any]``,
    whose parameters are NOT union members -- the distinction the substring
    test could not make.
    """
    base = ast.unparse(node.value).split(".")[-1]
    if base not in {"Optional", "Union"}:
        return None
    sl = node.slice
    elts = list(sl.elts) if isinstance(sl, ast.Tuple) else [sl]
    if base == "Optional":
        elts.append(ast.Constant(value=None))
    return elts


def _walk_union(node: ast.expr, members: list[str]) -> None:
    """Append the top-level union members of ``node`` to ``members``."""
    # `A | B` is a BinOp; `Optional[X]`/`Union[A, B]` are Subscripts.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        _walk_union(node.left, members)
        _walk_union(node.right, members)
        return
    if isinstance(node, ast.Subscript):
        elts = _union_subscript_elements(node)
        if elts is not None:
            for elt in elts:
                _walk_union(elt, members)
            return
    members.append(ast.unparse(node))


def _permits_none(ann: str) -> bool:
    """True if ``ann`` accepts None at the TOP level of the annotation."""
    for member in _top_level_union_members(ann):
        stripped = member.strip().strip("'\"")
        if stripped in _NONE_OK or stripped == "NoneType":
            return True
    return False


def _all_members_hostile(ann: str, hostile_bases: set[str]) -> bool:
    """True when EVERY top-level union member rejects the literal.

    A union is hostile only if none of its members accepts the value: `"x"`
    passed to `int | None` is a mismatch, but passed to `int | str` it is not.
    Comparing `ann.split("[")[0]` instead read only the first member, so
    `int | None` looked like base `int |` and matched nothing -- a false
    negative -- while member order silently decided the answer.
    """
    members = _top_level_union_members(ann)
    if not members:
        return False
    for member in members:
        base = member.split("[")[0].strip().strip("'\"")
        # A None member does not rescue a str/int literal -- `int | None`
        # rejects "x" just as `int` does -- so it does not make the union
        # permissive here. (It is the whole question for a None literal, which
        # _permits_none answers separately.)
        if base in {"None", "NoneType"}:
            continue
        if base not in hostile_bases:
            return False
    return True


def _is_mismatch(value: object, ann: str) -> bool:
    """Return True if the Python literal ``value`` is incompatible with ``ann``."""
    if value is None:
        return not _permits_none(ann)
    if isinstance(value, str):
        return _all_members_hostile(ann, _STR_HOSTILE_BASES)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _all_members_hostile(ann, _INT_HOSTILE_BASES)
    return False


# ---------------------------------------------------------------------------
# Call-site scanning
# ---------------------------------------------------------------------------

def _collect_imports(tree: ast.Module) -> dict[str, str]:
    """Map locally bound name -> module stem for ``from X import Y`` imports."""
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod_stem = node.module.split(".")[-1]
            for alias in node.names:
                local = alias.asname or alias.name
                imported[local] = mod_stem
    return imported


def _callee_name(node: ast.Call) -> str | None:
    """Return the bare function name from a Call node, or None if not resolvable."""
    func_node = node.func
    if isinstance(func_node, ast.Name):
        return func_node.id
    # Attribute calls are deliberately NOT resolved. Returning `.attr` discards
    # the receiver, so `a.foo()`, `b.foo()` and `self.foo()` become
    # indistinguishable and match any imported `foo`. Measured over tests/:
    # 38,141 attribute calls, 93 of which resolved against an unrelated
    # function -- e.g. `self._parse_agent({...})` matched to a module-level
    # import. The docstring always claimed these were skipped; now they are.
    return None


def _check_call_args(
    node: ast.Call,
    callee_name: str,
    path: str,
    src_path: str,
    src_lineno: int,
    params: list[tuple[str, str | None]],
) -> list[dict]:
    """Return mismatch findings for the positional literal arguments of one Call."""
    results: list[dict] = []
    for i, arg in enumerate(node.args):
        if not isinstance(arg, ast.Constant):
            continue
        if i >= len(params):
            continue
        param_name, ann = params[i]
        if ann is None:
            continue
        if not _is_mismatch(arg.value, ann):
            continue
        results.append(
            {
                "kind": "arg-type-mismatch",
                "call_site": f"{path}:{node.lineno}",
                "callee": callee_name,
                "param": param_name,
                "annotation": ann,
                "literal_value": repr(arg.value),
                "callee_defined_at": f"{src_path}:{src_lineno}",
            }
        )
    return results


def _scan_file(path: str, sigs: Sigs) -> list[dict]:
    """Return all mismatch findings from one test file."""
    tree = _parse_py(path)
    if tree is None:
        _STATS["test_files_unparsed"] += 1
        return []
    imported = _collect_imports(tree)
    findings: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node)
        if name is None or name not in imported:
            continue
        key = (imported[name], name)
        if key not in sigs:
            continue
        src_path, src_lineno, params = sigs[key]
        findings.extend(_check_call_args(node, name, path, src_path, src_lineno, params))
    return findings


def scan_test_files(test_root: str, sigs: Sigs) -> list[dict]:
    """Scan call sites in ``test_root`` for literal-type mismatches."""
    findings: list[dict] = []
    for path in _iter_py(test_root):
        _STATS["test_files_scanned"] += 1
        findings.extend(_scan_file(path, sigs))
    findings.sort(key=lambda f: (f["call_site"], f["callee"], f["param"]))
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    src_root = argv[1] if len(argv) > 1 else SRC_ROOT
    test_root = argv[2] if len(argv) > 2 else TEST_ROOT

    sigs = collect_signatures(src_root)
    findings = scan_test_files(test_root, sigs)

    # An empty scan is a tooling failure, not a clean result, so it exits
    # non-zero rather than printing a reassuring "0 findings". A wrong root, a
    # rename, or a tree that failed to parse would otherwise be byte-identical
    # to a genuinely clean run -- which is the false-clean class this detector
    # exists to work around, and would be embarrassing to reproduce in it.
    scanned_nothing = (
        _STATS["src_files_scanned"] == 0
        or _STATS["test_files_scanned"] == 0
        or _STATS["signatures_collected"] == 0
    )

    json.dump(
        {
            "src_root": src_root,
            "test_root": test_root,
            "total_findings": len(findings),
            "stats": dict(_STATS),
            "scanned_nothing": scanned_nothing,
            "note": (
                "Candidates only — not proven defects.  The resolver is heuristic: "
                "import-based, positional, literal-only.  A same-named function in "
                "an unrelated module can produce a false positive.  Read each finding "
                "before acting.  Check `stats` before trusting a zero: 0 findings with "
                "0 files scanned is a broken run, not a clean tree."
            ),
            "findings": findings,
        },
        sys.stdout,
        indent=2,
    )
    print()

    if scanned_nothing:
        print(
            f"ERROR: scanned nothing (src={src_root!r} test={test_root!r}); "
            "0 findings here means the run is broken, not that the tree is clean",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
