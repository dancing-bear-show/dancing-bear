"""AcroForm field filling helpers for PDF templates.

Government and insurance PDF templates ship with a single default font size
applied to every text widget, sized for the widest field on the form. Narrow
cells -- the three-part phone number, the yyyy/mm/dd date triples -- then
render with their contents pressed against the cell walls, or clipped
outright, while wide name fields look fine. The fix is per-field sizing:
shrink only the fields whose cells are narrow, and leave the rest alone.

PyMuPDF is imported lazily so importing this module never requires it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    import fitz

__all__ = [
    "DEFAULT_FONT_SIZES",
    "FALLBACK_FONT_SIZE",
    "font_size_for",
    "format_da",
    "pdf_string",
    "set_text_field",
    "fill_text_fields",
    "set_checkbox",
]

# Field-name prefix -> point size. Derived from Sun Life EHC/HSA claim forms,
# where the template default of 9pt overflows the narrow cells.
#
# The mapping is by prefix rather than exact name because these forms number
# their repeated rows ("4.DOB.year", "4.DOB.year2", ...) and a prefix covers
# every row without enumerating them.
DEFAULT_FONT_SIZES: dict[str, int] = {
    # Narrow single-purpose cells: date components and phone number segments.
    # 7pt is the largest size that leaves visible margin on a 3-digit cell.
    "dateOfBirth": 7,
    "2.day_phone.": 7,
    "4.DOB.": 7,
    "5.date.": 7,
    # Currency fields: wider than a date cell but still tight once a
    # thousands separator and two decimals are present.
    "3.total_claimed": 8,
}

# Applied to any field not matched by the size map: the template's own
# default, which suits the wide free-text fields (names, address, member ID).
FALLBACK_FONT_SIZE = 9


def font_size_for(
    field_name: str,
    sizes: Mapping[str, int] | None = None,
    fallback: int = FALLBACK_FONT_SIZE,
) -> int:
    """Return the point size for ``field_name`` by longest matching prefix.

    Longest-prefix wins, so a specific rule such as ``"4.DOB.year"`` overrides
    a broader ``"4."`` without depending on mapping order.

    >>> font_size_for("2.day_phone.area")
    7
    >>> font_size_for("lastName")
    9
    """
    table = DEFAULT_FONT_SIZES if sizes is None else sizes
    match = ""
    for prefix in table:
        if field_name.startswith(prefix) and len(prefix) > len(match):
            match = prefix
    return table[match] if match else fallback


def pdf_string(value: str) -> str:
    """Wrap ``value`` as a PDF literal string, escaping what must be escaped.

    Inside a literal string ``\\``, ``(`` and ``)`` are syntax, so a value
    carrying them cannot be interpolated raw. The failure modes are not
    symmetric and neither is loud:

    * a lone backslash is consumed as an escape introducer, so ``back\\slash``
      is stored as ``backslash`` -- silent data loss, no error raised;
    * an unbalanced ``)`` closes the string early and the rest is parsed as
      dictionary syntax, raising ``FzErrorSyntax: invalid key in dict``;
    * *balanced* parens happen to round-trip intact, which is what makes this
      easy to miss -- ``Smith (Jr)`` works, ``Smith (Jr`` does not.

    Names carrying either character are ordinary, so escape rather than
    reject.

    >>> pdf_string("Smith (Jr)")
    '(Smith \\\\(Jr\\\\))'
    >>> pdf_string("plain")
    '(plain)'
    """
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return f"({escaped})"


def format_da(size: int, font: str = "Helv", color: str = "0 g") -> str:
    """Build a ``/DA`` default-appearance value as a parenthesized PDF string.

    The parentheses are required. ``xref_set_key`` writes the value verbatim,
    so a bare ``0 g /Helv 7 Tf`` is not a PDF string literal and silently
    stores null -- which makes viewers auto-size the text *larger* than the
    template default, the opposite of the intent.

    >>> format_da(7)
    '(0 g /Helv 7 Tf)'
    """
    return pdf_string(f"{color} /{font} {size} Tf")


def _widget_index(doc: fitz.Document) -> list[tuple[str, int, str, list[str]]]:
    """Snapshot (field_name, xref, field_type, on_states) for every widget.

    Collected once up front because ``xref_set_key`` invalidates the live
    widget objects returned by ``page.widgets()`` -- including
    ``button_states()``, which is why the on-states are captured here rather
    than read back later.
    """
    return [
        (w.field_name, w.xref, w.field_type_string, _on_states(w))
        for pno in range(doc.page_count)
        for w in (doc[pno].widgets() or [])
    ]


def _on_states(widget: Any) -> list[str]:
    """Return a checkbox widget's non-``Off`` appearance states.

    ``button_states()`` returns None for non-button widgets, and for buttons
    may return a dict whose "normal" value is itself None -- so neither
    ``or {}`` nor ``.get(..., [])`` alone is enough to make this total.
    """
    states = widget.button_states()
    if not isinstance(states, dict):
        return []
    normal = states.get("normal") or []
    return [s for s in normal if s != "Off"]


def set_text_field(
    doc: fitz.Document,
    field_name: str,
    value: str,
    *,
    sizes: Mapping[str, int] | None = None,
    index: Iterable[tuple[str, int, str, list[str]]] | None = None,
) -> int:
    """Set every text widget named ``field_name`` to ``value``, sized to fit.

    Returns the number of widgets written. Zero means the name matched
    nothing -- worth asserting on, since a renamed field on a new template
    version fails silently otherwise.
    """
    widgets = list(index) if index is not None else _widget_index(doc)
    da = format_da(font_size_for(field_name, sizes))
    written = 0
    for name, xref, ftype, _states in widgets:
        if name != field_name or ftype not in ("Text", "ComboBox"):
            continue
        doc.xref_set_key(xref, "V", pdf_string(value))
        doc.xref_set_key(xref, "DA", da)
        # Drop the cached appearance stream so the viewer regenerates it
        # from the value and /DA we just wrote.
        doc.xref_set_key(xref, "AP", "null")
        written += 1
    return written


def fill_text_fields(
    doc: fitz.Document,
    values: Mapping[str, str],
    *,
    sizes: Mapping[str, int] | None = None,
    require_all: bool = True,
) -> dict[str, int]:
    """Fill many text fields, returning ``{field_name: widgets_written}``.

    With ``require_all`` (the default), a field that matched no widget raises
    ``KeyError`` rather than being skipped quietly.
    """
    index = _widget_index(doc)
    counts = {
        name: set_text_field(doc, name, value, sizes=sizes, index=index)
        for name, value in values.items()
    }
    if require_all:
        missing = sorted(n for n, c in counts.items() if c == 0)
        if missing:
            raise KeyError(f"no widget matched field name(s): {', '.join(missing)}")
    return counts


def set_checkbox(
    doc: fitz.Document,
    field_name: str,
    on_state: str | None,
    *,
    index: Iterable[tuple[str, int, str, list[str]]] | None = None,
) -> int:
    """Tick the widget whose on-state is ``on_state``; clear its siblings.

    Yes/No pairs on these forms share one field name and are distinguished
    only by their on-state, so setting the *field* ticks both boxes at once.
    Writing each widget's xref individually is what keeps that from happening.

    Pass ``on_state=None`` to clear every widget with this name.

    Note the on-state name is not a label: on the Sun Life forms the widget
    whose on-state is ``Yes`` sits beside the printed **No** for
    ``2.member_another_plan``. Confirm against a render, not the name.
    """
    widgets = list(index) if index is not None else _widget_index(doc)
    written = 0
    for name, xref, ftype, states in widgets:
        if name != field_name or ftype != "CheckBox":
            continue
        state = states[0] if states else None
        target = state if (on_state is not None and state == on_state) else "Off"
        doc.xref_set_key(xref, "AS", f"/{target}")
        doc.xref_set_key(xref, "V", f"/{target}" if target != "Off" else "null")
        doc.xref_set_key(xref, "AP", "null")
        written += 1
    return written
