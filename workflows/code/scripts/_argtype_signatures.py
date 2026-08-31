"""Signature collection pass for detect_arg_type_mismatch.

Walks a source tree, parses each .py file, and builds a table of annotated
function/method signatures keyed by (module_stem, funcname).

This module is an implementation detail of detect_arg_type_mismatch.py.  It
must not be imported directly from outside that script family.
"""

from __future__ import annotations

import ast
import os

from _argtype_common import (
    _AMBIGUOUS,
    _STATS,
    Sigs,
    _iter_py,
    _parse_py,
    _reset_stats,
)


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
    stripped -- that shifts every subsequent positional index and produces false
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
