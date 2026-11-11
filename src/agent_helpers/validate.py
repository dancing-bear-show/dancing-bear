"""Validators: Python imports, AST structure, and JSON files.

Each function returns a plain dict ready for JSON emission. Failures are
reported in the body (``status``/``valid``/``overall``), never raised.
"""

from __future__ import annotations

import ast
import importlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

PASS = "PASS"  # nosec B105 - verdict label, not a secret
FAIL = "FAIL"


# ---------------------------------------------------------------------------
# imports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolResult:
    name: str
    status: str  # PASS | FAIL
    error: str | None = None


def _overall(results: list[SymbolResult]) -> str:
    return PASS if all(r.status == PASS for r in results) else FAIL


def validate_symbols(module_name: str, symbols: list[str]) -> dict:
    """Import ``module_name`` and check each symbol exists as an attribute."""
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # module-level code in arbitrary imports can raise any type; reported, not swallowed
        results = [SymbolResult(s, FAIL, f"{type(exc).__name__}: {exc}") for s in symbols]
        return {"module": module_name, "symbols": [asdict(r) for r in results], "overall": FAIL}

    results = [
        SymbolResult(s, PASS)
        if hasattr(mod, s)
        else SymbolResult(s, FAIL, f"module {module_name!r} has no attribute {s!r}")
        for s in symbols
    ]
    return {"module": module_name, "symbols": [asdict(r) for r in results], "overall": _overall(results)}


def validate_import_order(module_names: list[str]) -> dict:
    """Import each module in sequence, reporting per-module status."""
    results: list[SymbolResult] = []
    for name in module_names:
        try:
            importlib.import_module(name)
            results.append(SymbolResult(name, PASS))
        except Exception as exc:  # module-level code in arbitrary imports can raise any type; reported, not swallowed
            results.append(SymbolResult(name, FAIL, f"{type(exc).__name__}: {exc}"))
    return {"modules": [asdict(r) for r in results], "overall": _overall(results)}


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

# Branch nodes that count toward nesting depth.
_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.Try,
    ast.ExceptHandler,
    ast.Match,
)


def nesting_depth(node: ast.AST, current: int = 0) -> int:
    """Return the maximum branch-nesting depth beneath ``node``.

    Each branch node increments the depth for its children; sibling branches
    do not accumulate.
    """
    depth = current + 1 if isinstance(node, _BRANCH_NODES) else current
    deepest = depth
    for child in ast.iter_child_nodes(node):
        deepest = max(deepest, nesting_depth(child, depth))
    return deepest


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the top-level function node with the given name, or None."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _all_list(tree: ast.Module) -> list[str] | None:
    """Return the string entries of a top-level ``__all__`` list, else None."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        is_all = any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
        if is_all and isinstance(node.value, (ast.List, ast.Tuple)):
            return [
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return None


def _defined_names(tree: ast.Module) -> set[str]:
    """Names bound at module top level (defs, classes, assignments, imports)."""
    defined: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined.update((a.asname or a.name).split(".")[0] for a in node.names)
    return defined


def _ast_failure(file: str, error: str, **extra: object) -> dict:
    return {"file": file, **extra, "status": FAIL, "error": error}


def check_all_exported(tree: ast.Module, file: str) -> dict:
    """Verify every name in ``__all__`` is bound at the module top level."""
    exported = _all_list(tree)
    if exported is None:
        return _ast_failure(file, "__all__ not found in module")
    undefined = [n for n in exported if n not in _defined_names(tree)]
    return {
        "file": file,
        "all_list": exported,
        "undefined": undefined,
        "status": PASS if not undefined else FAIL,
    }


def check_function_nesting(tree: ast.Module, file: str, func_name: str) -> dict:
    """Report the maximum branch-nesting depth of a top-level function."""
    fn_node = _find_function(tree, func_name)
    if fn_node is None:
        return _ast_failure(file, f"function {func_name!r} not found", function=func_name)
    depth = max((nesting_depth(child) for child in ast.iter_child_nodes(fn_node)), default=0)
    return {"file": file, "function": func_name, "nesting_depth": depth, "status": PASS}


def validate_ast(file: str, *, all_exported: bool, function: str | None) -> dict:
    """Parse ``file`` and run the requested structural check."""
    try:
        source = Path(file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _ast_failure(file, str(exc))
    try:
        tree = ast.parse(source, filename=file)
    except SyntaxError as exc:
        return _ast_failure(file, f"SyntaxError: {exc}")
    if all_exported:
        return check_all_exported(tree, file)
    return check_function_nesting(tree, file, function or "")


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def _check_keys(data: object, keys_arg: str | None) -> tuple[list[str], str | None]:
    """Verify each comma-separated key exists in ``data``; report the first missing."""
    if not keys_arg:
        return [], None
    present: list[str] = []
    for key in (k.strip() for k in keys_arg.split(",") if k.strip()):
        if not (isinstance(data, dict) and key in data):
            return present, f"--keys {key!r}: key not found"
        present.append(key)
    return present, None


def _check_count(data: object, count_arg: str | None) -> tuple[dict[str, int], str | None]:
    """Measure the list length at ``count_arg`` in ``data``, if requested."""
    if not count_arg:
        return {}, None
    key = count_arg.strip()
    if not isinstance(data, dict) or key not in data:
        return {}, f"--count {key!r}: key not found"
    value = data[key]
    if not isinstance(value, list):
        return {}, f"--count {key!r}: value is {type(value).__name__}, not a list"
    return {key: len(value)}, None


def validate_json(file: str, keys: str | None, count: str | None) -> dict:
    """Parse ``file`` as JSON; optionally verify top-level keys and a list length.

    ``valid`` reflects parseability only; a missing key or non-list count is
    reported in ``error`` while ``valid`` stays true.
    """
    try:
        raw = Path(file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"valid": False, "file": file, "keys": [], "counts": {}, "error": str(exc)}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"valid": False, "file": file, "keys": [], "counts": {}, "error": f"JSON parse error: {exc}"}
    present, key_error = _check_keys(data, keys)
    counts, count_error = _check_count(data, count)
    return {"valid": True, "file": file, "keys": present, "counts": counts, "error": key_error or count_error}
