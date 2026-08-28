"""Inline emphasis markup for candidate prose.

Candidate data carries a deliberately tiny markup vocabulary so that a
reference resume's short bolded key phrases can be authored in the data
instead of being inferred by the renderer:

* ``**bold**`` renders a bold run
* ``*italic*`` renders an italic run

Everything else is literal. This is NOT Markdown, and the difference is the
point -- a resume is full of characters Markdown would claim. In particular:

UNDERSCORES ARE NOT MARKUP
    ``_x_`` and ``__x__`` render literally. A technical resume is full of
    identifiers (``some_function_name``), file names (``docx_renderers.py``)
    and env vars (``__init__``), and treating ``_`` as emphasis would mangle
    all of them into partially-italic garbage that no author asked for.
    Asterisks are rarer in that content and are the only delimiter honoured.

UNMATCHED DELIMITERS RENDER LITERALLY
    ``"5 * 3 = 15"``, ``"a * b"`` and ``"**unclosed"`` survive byte-for-byte.
    A parser that swallowed text on an unbalanced delimiter would silently
    delete resume content, which is far worse than declining to emphasise.

INTRA-WORD ASTERISKS ARE NOT DELIMITERS
    ``file*.txt`` and ``a*b`` stay literal. An opening delimiter must be
    followed by a non-space, a closing delimiter must be preceded by a
    non-space, AND the pair must not both sit flush against word characters
    on their outer edges -- see ``_opens_at``/``_closes_at``.

NESTING IS UNSUPPORTED, AND DEGRADES PREDICTABLY
    ``**a *b* c**`` yields one bold span whose text is the literal ``a *b* c``
    -- the inner delimiters are not re-scanned and are not stripped. The
    alternative (dropping them) would silently rewrite the text. Emphasis
    does not nest in this vocabulary; authors who need both should not.
"""
from __future__ import annotations

from dataclasses import dataclass

# The only two delimiters. Ordered longest-first so ``**`` is tested before
# ``*`` at the same index -- the reverse would parse ``**x**`` as an italic
# span containing an empty string followed by literal junk.
_BOLD = "**"
_ITALIC = "*"


@dataclass(frozen=True)
class MarkupSpan:
    """One contiguous run of text carrying resolved emphasis flags.

    ``text`` is the literal string to render -- delimiters are already
    stripped for a matched span, and retained for text that never matched.
    """

    text: str
    bold: bool = False
    italic: bool = False


def _is_word_char(ch: str) -> bool:
    """Whether ``ch`` binds a delimiter into a surrounding word."""
    return ch.isalnum() or ch == "_"


def _opens_at(text: str, idx: int, delim: str) -> bool:
    """Whether a delimiter at ``idx`` can open an emphasis span.

    An opener must be followed by a non-space (so ``"a * b"`` cannot open),
    and must not be glued to a word character on its left (so the ``*`` in
    ``file*.txt`` cannot open).
    """
    after = idx + len(delim)
    if after >= len(text) or text[after].isspace():
        return False
    return not (idx > 0 and _is_word_char(text[idx - 1]))


def _closes_at(text: str, idx: int, delim: str) -> bool:
    """Whether a delimiter at ``idx`` can close an emphasis span.

    A closer must be preceded by a non-space (so ``"a * b"`` cannot close),
    and must not be glued to a word character on its right (so the ``*`` in
    ``a*b`` cannot close).
    """
    if idx == 0 or text[idx - 1].isspace():
        return False
    after = idx + len(delim)
    return not (after < len(text) and _is_word_char(text[after]))


def _find_close(text: str, start: int, delim: str) -> int:
    """Index of the closing ``delim`` at or after ``start``, or -1.

    For ``*`` a candidate position that actually begins a ``**`` is skipped,
    so ``*a**b*`` does not close on the first half of the ``**``.
    """
    idx = start
    while (idx := text.find(delim, idx)) != -1:
        if delim == _ITALIC and text.startswith(_BOLD, idx):
            idx += len(_BOLD)
            continue
        if _closes_at(text, idx, delim):
            return idx
        idx += len(delim)
    return -1


def _match_at(text: str, idx: int) -> tuple[str, str, int] | None:
    """Try to match an emphasis span starting at ``idx``.

    Returns ``(delimiter, inner_text, end_index)`` where ``end_index`` is the
    first index after the closing delimiter, or ``None`` when no span opens
    here. An empty body (``****``, ``**``) never matches, so empty emphasis
    cannot produce an empty run.

    A ``**`` at ``idx`` is only ever considered as bold. Falling through to
    the italic branch on the same index would let ``****`` parse as an italic
    span wrapping a literal ``**`` -- emphasis conjured out of what the author
    wrote as empty emphasis. When ``**`` fails to open or close, both of its
    asterisks stay literal.
    """
    for delim in (_BOLD, _ITALIC):
        if not text.startswith(delim, idx):
            continue
        if not _opens_at(text, idx, delim):
            return None
        body_start = idx + len(delim)
        close = _find_close(text, body_start, delim)
        if close == -1 or close == body_start:
            return None
        return delim, text[body_start:close], close + len(delim)
    return None


def parse_inline_markup(text: str) -> list[MarkupSpan]:
    """Split ``text`` into emphasis spans.

    Text with no markup yields exactly one span, so a plain string is never
    gratuitously split into several runs. An empty string yields no spans.
    Consecutive literal characters are coalesced into a single span rather
    than emitted one character at a time.
    """
    if not text:
        return []

    spans: list[MarkupSpan] = []
    literal: list[str] = []
    idx = 0

    def flush() -> None:
        if literal:
            spans.append(MarkupSpan("".join(literal)))
            literal.clear()

    while idx < len(text):
        matched = _match_at(text, idx)
        if matched is None:
            literal.append(text[idx])
            idx += 1
            continue
        delim, body, idx = matched
        flush()
        spans.append(MarkupSpan(body, bold=delim == _BOLD, italic=delim == _ITALIC))

    flush()
    return spans


def has_inline_markup(text: str) -> bool:
    """Whether ``text`` contains at least one span that would be emphasised."""
    return any(s.bold or s.italic for s in parse_inline_markup(text))


def strip_inline_markup(text: str) -> str:
    """Return ``text`` with matched delimiters removed and literals intact.

    Used where a caller needs the rendered characters without the runs --
    e.g. the plain-text line a section renderer reports back to its caller.
    """
    return "".join(s.text for s in parse_inline_markup(text))
