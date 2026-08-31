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
  are resolved.  Attribute calls (``obj.method()``) are not checked.
- Only positional arguments are inspected.  Keyword arguments are not.
- A function defined in module ``foo`` and one in module ``bar`` with the same
  name can collide: if both are imported and one call is made, the detector may
  map it to the wrong signature.
- The resolver is heuristic, not a type-checker.  Verify each finding before
  acting on it.

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


def _has_classmethod_decorator(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "classmethod":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "classmethod":
            return True
    return False


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
        params = _collect_params(member, is_method=not is_cm, is_classmethod=is_cm)
        sigs[(mod, member.name)] = (path, member.lineno, params)


def collect_signatures(src_root: str) -> Sigs:
    """Walk ``src_root`` and collect annotated function/method signatures."""
    sigs: Sigs = {}
    for path in _iter_py(src_root):
        tree = _parse_py(path)
        if tree is None:
            continue
        mod = os.path.splitext(os.path.basename(path))[0]
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _collect_params(node, is_method=False, is_classmethod=False)
                sigs[(mod, node.name)] = (path, node.lineno, params)
            elif isinstance(node, ast.ClassDef):
                _collect_class_sigs(node, path, mod, sigs)
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


def _is_mismatch(value: object, ann: str) -> bool:
    """Return True if the Python literal ``value`` is incompatible with ``ann``."""
    if value is None:
        return not any(tok in ann for tok in _NONE_OK)
    if isinstance(value, str):
        return ann.split("[")[0].strip() in _STR_HOSTILE_BASES
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ann.split("[")[0].strip() in _INT_HOSTILE_BASES
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
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
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

    json.dump(
        {
            "src_root": src_root,
            "test_root": test_root,
            "total_findings": len(findings),
            "note": (
                "Candidates only — not proven defects.  The resolver is heuristic: "
                "import-based, positional, literal-only.  A same-named function in "
                "an unrelated module can produce a false positive.  Read each finding "
                "before acting."
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
