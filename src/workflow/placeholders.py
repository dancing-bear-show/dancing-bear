"""One grammar for ``{name}`` placeholder scanning and substitution.

All workflow modules that find or replace ``{name}`` placeholders — the
compiler, linter, harness-outputs checker, and criteria resolver — use this
module so the rules are defined once.

Grammar
-------
An identifier is ``[A-Za-z_]\\w*`` (ASCII).  A **placeholder** is ``{ident}``
where the ``{`` is not immediately preceded by another ``{``.  ``{{ident}}``
is NOT a placeholder — the doubled braces render verbatim — and neither is a
non-identifier token such as a regex quantifier like ``{2,40}``.

API
---
``find_refs(text, *, skip_code=False) -> set[str]``
    All placeholder names in *text*.  With ``skip_code=True`` names inside
    backtick code spans are excluded (used by the linter's
    undeclared-variable check, where a code example should not trigger a
    warning about an unknown param).

``substitute(text, mapping) -> str``
    Replace ``{key}`` with the corresponding value for every identifier-shaped
    key in *mapping*.  Unknown placeholders are left as-is.  ``{{key}}`` is
    left as-is (it is not a placeholder).

``in_backtick_span(line, pos) -> bool``
    True if character position *pos* on *line* falls inside a backtick code
    span (an odd count of backticks precedes it).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = [
    "IDENTIFIER_RE",
    "find_refs",
    "in_backtick_span",
    "is_identifier",
    "substitute",
]

# [A-Za-z_]\w* (ASCII).  A bare \w admits Unicode letters, so ASCII is required
# to stay faithful to the grammar described in the module docstring.
IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)

# Matches {ident} but NOT {{ident}} or ${ident}.
# - (?<![{\$]) negative lookbehind: skip when { is preceded by another { (so
#   {{name}} is not a placeholder — it renders verbatim) or by $ (so ${VAR}
#   is not a placeholder — it is shell variable expansion, not a workflow param).
# - No closing-brace lookahead: {name} inside a JSON wrapper such as
#   '{"value": {name}}' is a valid placeholder and must be found.
_PLACEHOLDER_RE = re.compile(r"(?<![{$])\{([A-Za-z_]\w*)\}", re.ASCII)


def is_identifier(name: str) -> bool:
    """True if *name* is a valid ``[A-Za-z_]\\w*`` (ASCII) placeholder name."""
    return IDENTIFIER_RE.fullmatch(name) is not None


def find_refs(text: str, *, skip_code: bool = False) -> set[str]:
    """Return all placeholder names in *text*.

    A placeholder is ``{ident}`` where ``ident`` passes :func:`is_identifier`
    and the ``{`` is not immediately preceded by another ``{``.

    Args:
        text: The text to scan.
        skip_code: When True, references inside backtick code spans on the
            same line are excluded.  Useful for the linter's undeclared-
            variable check where a code example should not produce a warning.

    Returns:
        A ``set[str]`` of placeholder names (without braces).
    """
    if not skip_code:
        return {m.group(1) for m in _PLACEHOLDER_RE.finditer(text)}

    result: set[str] = set()
    for line in text.splitlines():
        for m in _PLACEHOLDER_RE.finditer(line):
            if not in_backtick_span(line, m.start()):
                result.add(m.group(1))
    return result


def in_backtick_span(line: str, pos: int) -> bool:
    """True if character position *pos* on *line* is inside a backtick span.

    A position is inside a backtick span when an odd number of backtick
    characters precede it on the same line.
    """
    return line[:pos].count("`") % 2 == 1


def substitute(text: str, mapping: Mapping[str, str]) -> str:
    """Replace ``{key}`` with the corresponding value for identifier-shaped keys.

    Uses :data:`_PLACEHOLDER_RE` so the scanner and the replacer share one
    grammar: a match is replaced only when its captured name is a key in
    *mapping*.  This guarantees:

    * ``{{key}}`` is NOT a placeholder and is left as-is (the lookbehind in
      the regex skips ``{{``-prefixed braces).
    * ``${key}`` is NOT a placeholder and is left as-is (the lookbehind also
      skips ``$``-prefixed braces).
    * Non-identifier tokens such as ``{2,40}`` are never matched.
    * Unknown placeholder names are left as-is.
    * Substitution is a single pass — a value that contains ``{x}`` is not
      re-expanded.

    This is the canonical substitution logic for all workflow modules.
    """

    def _replace(m: re.Match[str]) -> str:
        name = m.group(1)
        return mapping[name] if name in mapping else m.group(0)

    return _PLACEHOLDER_RE.sub(_replace, text)
