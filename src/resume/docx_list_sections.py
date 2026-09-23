"""List-section rendering for resume DOCX output.

Provides ListSectionRenderer for simple list sections such as interests,
languages, certifications, and coursework.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .docx_bullets import BulletRenderer
from .docx_styles import TextFormatter
from .schema import _Item

if TYPE_CHECKING:
    from .schema import Resume

_logger = logging.getLogger(__name__)


def join_name_desc(name: str, desc: str, desc_sep: str) -> str:
    """Join a name and description, omitting the separator when desc is empty.

    Callers differ in how they clean the halves — some clean the joined result,
    others each half independently — so this joins only and leaves cleaning to
    the caller.
    """
    return f"{name}{desc_sep}{desc}" if desc else name


class ListSectionRenderer:
    """Renders simple list sections (interests, languages, etc.)."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        self.doc = doc
        self.bullets = BulletRenderer(doc, page_cfg)
        self.text = TextFormatter()

    def render(self, resume: "Resume", *args: Any, **kwargs: Any) -> Any:
        """Render the section into the document. Overridden by each subclass."""
        raise NotImplementedError(f"{type(self).__name__} must implement render()")

    def _extract_item_text(
        self, it: Any, name_keys: tuple, desc_key: str | None, desc_sep: str
    ) -> str | None:
        """Extract and format text from a single item.

        Three input shapes reach here, and each resolves its display name a
        different way:

        * a schema item -- the alias spellings ``name_keys`` used to search for
          (``language``, ``course``, ``cert``, ...) are already resolved by
          ``Resume.from_dict`` onto the canonical primary field, so the value
          is read from there. ``name_keys`` is still consulted, but only to
          decide whether the spelling the value *arrived under* is one this
          renderer accepts -- see ``_item_name``.
        * a plain dict -- ``teaching`` is deliberately untyped
          (``list[Any]``), so its entries arrive as raw dicts and still need
          the key search.
        * a bare scalar -- stringified.

        ``desc_key`` names a *field* in both the typed and dict cases, so it is
        read positionally rather than translated.
        """
        if isinstance(it, _Item):
            return self._format_name_desc(
                self._item_name(it, name_keys),
                self._item_desc(it, desc_key),
                desc_sep,
            )
        if isinstance(it, dict):
            name = next((str(it.get(k) or "").strip() for k in name_keys if it.get(k)), "")
            desc = str(it.get(desc_key) or "").strip() if desc_key else ""
            return self._format_name_desc(name, desc, desc_sep)
        s = str(it).strip()
        return self.text.clean_inline(s) if s else None

    @staticmethod
    def _item_name(it: _Item, name_keys: tuple) -> str:
        """Return a schema item's display text, honouring the renderer's keys.

        The value is read from the item's own primary field, because the
        sections routed through here do NOT share one: ``interests`` items are
        ``PriorityItem`` and carry their text in ``text``, while
        ``languages``/``coursework``/``certifications`` items carry it in
        ``name``. Reading ``name`` from every item would leave every interest
        blank -- a section that renders as nothing without raising, which
        nothing outside the goldens would notice.

        ``name_keys`` is searched in the RENDERER's order, not the schema's.
        The two disagree, and the disagreement is observable: ``PriorityItem``
        aliases ``text`` as ``("text", "line", "name")`` while this renderer
        accepts ``("name", "title", "label", "text")``. For an item spelled
        ``{"name": "Cycling", "text": "Chess"}`` the schema resolves ``text``
        onto the primary field and files ``name`` in ``extra``; reading the
        primary field alone would render "Chess" where the pre-migration dict
        path rendered "Cycling". Consulting ``name_keys`` in order against the
        original spellings -- the primary field's replayed key, plus whatever
        losing spellings ``extra`` retained -- reproduces the dict path exactly.

        A spelling the renderer does not list still yields ``""``. The schema's
        alias tuples remain a superset of what each renderer accepts, so a
        section can still decline a spelling its item type resolves. That
        gap is how ``label``-keyed entries in ``certifications``,
        ``coursework`` and ``languages`` used to render as nothing: the schema
        resolved ``label`` onto ``name``, but those renderers passed name_keys
        that omitted ``label``, so every key missed and the entry silently
        vanished under its own section heading. Those three now list ``label``
        last, which makes such entries render while leaving precedence intact
        -- an item carrying both ``name`` and ``label`` still displays
        ``name``.
        """
        primary = type(it)._primary_field()
        if not primary:
            return ""
        primary_key = it._replayed_key(primary)
        if not name_keys:
            return str(getattr(it, primary, "") or "").strip()
        for key in name_keys:
            value = getattr(it, primary, "") if key == primary_key else it.extra.get(key)
            if text := str(value or "").strip():
                return text
        return ""

    @staticmethod
    def _item_desc(it: _Item, desc_key: str | None) -> str:
        """Read a schema item's description field by name.

        Every ``desc_key`` the section renderers pass is a declared field on
        the matching item type: ``level`` on ``NamedLevelItem``, ``desc`` on
        ``CourseworkItem``, ``year`` on ``CertificationItem``. A key that is
        not declared reads back empty and its content disappears from the
        rendered section, so a new ``desc_key`` must be added to the schema
        rather than left to survive in ``extra``.
        """
        if not desc_key:
            return ""
        return str(getattr(it, desc_key, "") or "").strip()

    def _format_name_desc(self, name: str, desc: str, desc_sep: str) -> str | None:
        """Join a name and an optional description, cleaning the result.

        A description is only appended when there is a name to attach it to,
        matching the pre-migration behaviour: a description-only item renders
        as nothing rather than as a bare separator followed by text.
        """
        if not name:
            return None
        return self.text.clean_inline(join_name_desc(name, desc, desc_sep))

    def render_simple_list(
        self,
        items: list[Any],
        sec: dict[str, Any] | None = None,
        *,
        name_keys: tuple = ("name", "title", "label", "text"),
        desc_key: str | None = None,
        desc_sep: str = " — ",
    ) -> list[str]:
        """Normalize and render a simple list section, one bullet per item.

        ``bullets: false`` used to select a second rendering path here that
        joined every item into a single paragraph with ``separator`` (default
        " • ") between them. That put the bullet glyph *inside* the text, so
        Word had no line break to wrap on and rendered the section as one
        block of prose with glyphs buried in it -- the same defect the skills
        path was unified to remove. No shipped template selected it, so it was
        unreachable from this repo's own configs.

        The flag is now ignored and every item gets its own bullet paragraph.
        A hand-written template still carrying ``bullets: false`` is warned
        about rather than silently re-rendered, because the layout changes and
        an unexplained change is harder to act on than a message naming the
        key. Warning rather than raising matches the advisory convention used
        for template validation elsewhere.
        """
        cfg = sec or {}
        lines = [
            txt for it in items
            if (txt := self._extract_item_text(it, name_keys, desc_key, desc_sep))
        ]

        if lines:
            if not cfg.get("bullets", True):
                _logger.warning(
                    "section config sets 'bullets: false', which is no longer "
                    "honoured: list items always render as one bullet per line. "
                    "Remove the key to silence this warning."
                )
            self.bullets.add_bullets(lines, glyph=self.bullets.resolve_glyph(sec))

        return lines
