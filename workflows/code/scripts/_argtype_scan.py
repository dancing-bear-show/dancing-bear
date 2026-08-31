"""Call-site scanning pass for detect_arg_type_mismatch.

Walks a test tree and checks each call whose callee was explicitly imported
via ``from X import Y`` against the collected signature table.

This module is an implementation detail of detect_arg_type_mismatch.py.  It
must not be imported directly from outside that script family.
"""

from __future__ import annotations

import ast

from _argtype_common import (
    _STATS,
    Sigs,
    _iter_py,
    _parse_py,
)
from _argtype_types import _is_mismatch


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
