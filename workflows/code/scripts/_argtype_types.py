"""Type-compatibility predicates for detect_arg_type_mismatch.

Determines whether a Python literal value (None, str, int, float) is
incompatible with a given annotation string.  Annotations are inspected as
PARSED syntax, not resolved types.

This module is an implementation detail of detect_arg_type_mismatch.py.  It
must not be imported directly from outside that script family.
"""

from __future__ import annotations

import ast

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
