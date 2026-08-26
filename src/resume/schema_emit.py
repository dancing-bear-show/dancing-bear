"""Emit a JSON Schema (draft-07) for the resume dataclass tree.

Stdlib only -- no pydantic, no runtime dependency. Walks
``dataclasses.fields()`` recursively from :class:`resume.schema.Resume`.

Annotation resolution
---------------------
``schema.py`` uses ``from __future__ import annotations``, so every
``dataclasses.Field.type`` is a **string**, not a type object. Reading
``f.type`` directly (as a naive implementation does) makes every field fall
through to the permissive default and emits a schema that looks plausible but
describes nothing. Types are therefore resolved once per class with
``typing.get_type_hints`` and looked up by field name.

Bookkeeping fields (``extra``, ``_present``) carry round-trip state, not
document shape, and are excluded from the emitted schema.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any

from .schema import Resume, _Item

__all__ = ["emit_schema", "dataclass_schema"]

_PY_TO_JSON: dict[Any, str] = {
    str: "string",
    float: "number",
    int: "integer",
    bool: "boolean",
}

# Permissive fallback for Any-typed and unresolved annotations. Deliberate:
# `teaching` and `contact` are untyped by design, so there is no shape to
# assert -- this is not a validation gap being papered over.
_PERMISSIVE: dict[str, Any] = {}


def _resolve_hints(cls: type) -> dict[str, Any]:
    """Resolve a dataclass's string annotations to real type objects."""
    try:
        return typing.get_type_hints(cls)
    except (NameError, TypeError):
        # A forward reference that cannot be resolved degrades to permissive
        # rather than raising -- emitting is never worth crashing a caller.
        return {}


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    """Return ``(inner, is_optional)`` for ``X | None`` / ``Optional[X]``."""
    if typing.get_origin(tp) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return tp, False


def _field_schema(tp: Any) -> dict[str, Any]:
    """JSON Schema fragment for a single resolved annotation."""
    tp, optional = _unwrap_optional(tp)
    origin = typing.get_origin(tp)

    if origin is list:
        args = typing.get_args(tp)
        item_tp = args[0] if args else str
        schema: dict[str, Any] = {"type": "array", "items": _field_schema(item_tp)}
    elif dataclasses.is_dataclass(tp):
        schema = dataclass_schema(tp)
    elif tp in _PY_TO_JSON:
        schema = {"type": _PY_TO_JSON[tp]}
    elif tp is dict or origin is dict:
        schema = {"type": "object"}
    else:
        schema = dict(_PERMISSIVE)

    if optional and "type" in schema:
        schema["type"] = [schema["type"], "null"]
    return schema


def _emitted_fields(cls: type) -> list[dataclasses.Field]:
    """Document-shape fields, excluding round-trip bookkeeping."""
    internal = getattr(cls, "_INTERNAL", frozenset())
    return [f for f in dataclasses.fields(cls) if f.name not in internal]


def _has_default(f: dataclasses.Field) -> bool:
    return f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING


def dataclass_schema(cls: type) -> dict[str, Any]:
    """JSON Schema object fragment for one dataclass."""
    hints = _resolve_hints(cls)
    props: dict[str, Any] = {}
    required: list[str] = []

    for f in _emitted_fields(cls):
        props[f.name] = _field_schema(hints.get(f.name, Any))
        if not _has_default(f):
            required.append(f.name)

    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def emit_schema(root_cls: type | None = None) -> dict[str, Any]:
    """Emit the draft-07 JSON Schema document for ``root_cls``.

    Every field of every schema dataclass has a default, so ``required`` is
    empty throughout. That is intentional -- the on-disk format treats all
    sections as optional -- and is documented rather than assumed, since a
    consumer validating against this schema should know why nothing is
    required.
    """
    root = root_cls or Resume
    if not (isinstance(root, type) and issubclass(root, _Item)):
        raise TypeError(f"expected a resume schema dataclass, got {root!r}")
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": root.__name__,
        **dataclass_schema(root),
    }
