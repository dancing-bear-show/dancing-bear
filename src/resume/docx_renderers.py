"""Base DOCX renderers for resume content.

Provides BulletRenderer, HeaderRenderer, and ListSectionRenderer base classes.
"""
from __future__ import annotations

from typing import Any

from .docx_styles import StyleManager, TextFormatter
from .render_config import HeaderLineConfig, MetaRunConfig
from .schema import _Item

# The paragraph style every bulleted line in the standard layout carries. Set
# explicitly on each bullet paragraph rather than inherited from the document
# default, so the single-mechanism contract holds for any document this
# renderer is handed, including one whose default style is not ``Normal``.
NORMAL_PARAGRAPH_STYLE = "Normal"


class BulletRenderer:
    """Renders bullet lists with various styles."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        self.doc = doc
        self.page_cfg = page_cfg or {}
        self.styles = StyleManager()
        self.text = TextFormatter()

    def resolve_glyph(self, sec: dict[str, Any] | None) -> str:
        """Resolve the bullet glyph for a section, falling back to page config.

        Section config wins over page config, and both default to ``"•"``.

        The companion ``style`` key that used to be read alongside the glyph
        (``bullets.style``, ``plain_bullets``) selected between two different
        bullet mechanisms and no longer does anything -- there is only one. It
        is still accepted in config and simply ignored, so existing templates
        keep loading; only the glyph is honoured. See ``new_bullet_paragraph``.
        """
        for cfg in (sec, self.page_cfg):
            if cfg and isinstance(cfg.get("bullets"), dict):
                if glyph := (cfg["bullets"] or {}).get("glyph"):
                    return str(glyph)
        return "•"

    def new_bullet_paragraph(self, glyph: str = "•"):
        """Start the one and only kind of bulleted paragraph this layout emits.

        THIS IS THE SINGLE BULLET MECHANISM for the standard layout. Every
        bulleted line in every section -- summary, skills, experience,
        presentations, teaching, certifications, interests, languages,
        coursework -- must originate here, so that all of them share one style
        and one left edge and can therefore line up with each other.

        The paragraph is explicitly styled ``Normal`` rather than left to the
        document default, so the single-mechanism guarantee does not depend on
        what that default happens to be. It carries a literal ``"<glyph> "``
        run and is flushed to ``left_indent=0`` / ``first_line_indent=0``.
        That matches the reference document this output is styled after, which
        uses ``Normal`` throughout and contains no ``List Bullet`` paragraphs
        at all.

        WHY NOT ``List Bullet``
            Word's ``List Bullet`` style draws its glyph from a numbering
            definition in ``word/numbering.xml`` and carries that definition's
            own indent, which is NOT the paragraph indent and is not reset by
            ``flush_left``. Sections that used it therefore rendered at a
            different left edge from sections that printed a literal glyph, and
            no amount of per-section indent tuning could reconcile the two --
            they are different systems. The standard layout used to mix three
            such mechanisms (``List Bullet``, literal-glyph-with-indent-reset,
            and literal-glyph-with-no-indent-reset), which is exactly why its
            sections could not be aligned.

        Adding a second way to emit a bullet is how the three-mechanism split
        happened in the first place. Route new callers through here instead.
        """
        p = self.doc.add_paragraph(style=NORMAL_PARAGRAPH_STYLE)
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)
        p.add_run(f"{glyph} ")
        return p

    def _add_text_with_optional_keywords(self, p, text: str, keywords: list[str] | None) -> None:
        """Add text to a paragraph, bolding keyword matches if any are given."""
        if keywords:
            self._bold_keywords(p, text, keywords)
        else:
            p.add_run(text)

    def add_bullet_line(
        self,
        text: str,
        *,
        keywords: list[str] | None = None,
        glyph: str = "•",
    ):
        """Add a bullet line (glyph + text) via the shared bullet mechanism."""
        p = self.new_bullet_paragraph(glyph)
        self._add_text_with_optional_keywords(p, text, keywords)
        return p

    def add_named_bullet(
        self,
        name: str,
        desc: str,
        *,
        sec: dict[str, Any] | None = None,
        glyph: str = "•",
        sep: str = ": ",
    ):
        """Add a bullet with bold name and plain description.

        A name with no description emits the bold name alone. The separator
        and description runs are skipped rather than added empty, so such an
        item carries no dangling separator and no zero-length runs -- an empty
        run is invisible on the page but real in the XML, and would otherwise
        make a name-only bullet indistinguishable from one whose description
        was silently dropped.
        """
        p = self.new_bullet_paragraph(glyph)

        cfg = sec or {}
        name_color = cfg.get("name_color") or cfg.get("item_color") or cfg.get("title_color")

        r_name = p.add_run(name)
        r_name.bold = True
        self.styles.apply_run_color(r_name, name_color)

        if desc:
            if sep:
                p.add_run(sep)
            p.add_run(desc)
        return p

    def add_bullets(
        self,
        items: list[str],
        *,
        keywords: list[str] | None = None,
        glyph: str = "•",
    ) -> None:
        """Render a list of bullet items through the shared bullet mechanism.

        There is deliberately no ``plain``/``list_style`` switch here any more.
        It used to select between a literal-glyph paragraph and a Word
        ``List Bullet`` paragraph, and because different sections resolved that
        switch differently, the same document rendered its bullets at two
        different left edges. See ``new_bullet_paragraph``.
        """
        for it in items:
            self.add_bullet_line(it, keywords=keywords, glyph=glyph)

    @staticmethod
    def _find_earliest_keyword(lowered: str, text: str, keywords: list[str], from_idx: int):
        """Find the earliest occurring keyword in text from from_idx. Returns (pos, matched_text) or (None, None)."""
        match_pos = None
        match_kw = None
        for kw in keywords:
            if not kw:
                continue
            pos = lowered.find(kw.lower(), from_idx)
            if pos != -1 and (match_pos is None or pos < match_pos):
                match_pos = pos
                match_kw = text[pos:pos + len(kw)]
        return match_pos, match_kw

    def _bold_keywords(self, paragraph, text: str, keywords: list[str]):
        """Add text with keywords bolded.

        The loop already emits the remaining text before breaking, so the
        trailing fallback must not run when it did. Previously both fired when
        no keyword matched — `idx` was still 0 at the break — and every
        unmatched bullet rendered its text TWICE, concatenated with no
        separator ("...at scaleInstrumented and monitored...").
        """
        lowered = text.lower()
        idx = 0
        emitted = False

        while idx < len(text):
            match_pos, match_kw = self._find_earliest_keyword(lowered, text, keywords, idx)

            if match_pos is None:
                paragraph.add_run(text[idx:])
                emitted = True
                break

            if match_pos > idx:
                paragraph.add_run(text[idx:match_pos])

            br = paragraph.add_run(match_kw or "")
            br.bold = True
            emitted = True
            idx = match_pos + len(match_kw or "")

        if not emitted:
            paragraph.add_run(text)


class HeaderRenderer:
    """Renders header lines for experience and education entries."""

    def __init__(self, doc):
        self.doc = doc
        self.styles = StyleManager()

    def _parse_meta_pt(self, cfg: dict[str, Any]) -> float | None:
        """Parse meta_pt from config, returning None if invalid."""
        val = cfg.get("meta_pt")
        if not val:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _add_bold_colored_run(self, p, text: str, color: str | None):
        """Add a bold run with an optional color applied."""
        r = p.add_run(text)
        r.bold = True
        self.styles.apply_run_color(r, color)
        return r

    def _add_meta_run(self, p, text: str, cfg: MetaRunConfig):
        """Add a metadata run (location or duration) with optional brackets."""
        p.add_run(" — ")
        if cfg.brackets:
            p.add_run(cfg.open_br)
        r = p.add_run(text)
        if cfg.italic:
            r.italic = True
        self.styles.apply_run_size(r, cfg.meta_pt)
        self.styles.apply_run_color(r, cfg.color)
        if cfg.brackets:
            p.add_run(cfg.close_br)

    def add_header_line(
        self,
        content: HeaderLineConfig | None = None,
        *,
        sec: dict[str, Any] | None = None,
    ):
        """Add a formatted header line.

        Format: Title at Company — [Location] — (Duration)

        Args:
            content: Text and style fields for the header. Defaults to HeaderLineConfig().
            sec: Section config dict (colors, bracket flags, etc.).
        """
        c = content or HeaderLineConfig()
        cfg = sec or {}
        p = self.doc.add_paragraph(style=c.style)
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)

        item_color = cfg.get("item_color") or cfg.get("header_color")
        loc_color = cfg.get("location_color") or item_color
        dur_color = cfg.get("duration_color") or cfg.get("location_color") or item_color
        meta_pt = self._parse_meta_pt(cfg)

        # Title
        if c.title_text:
            self._add_bold_colored_run(p, c.title_text, item_color)

        # Company
        if c.title_text and c.company_text:
            p.add_run(" at ")
        if c.company_text:
            self._add_bold_colored_run(p, c.company_text, item_color)

        # Location
        if c.loc_text:
            self._add_meta_run(p, c.loc_text, MetaRunConfig(
                brackets=cfg.get("location_brackets", True),
                open_br="[", close_br="]",
                meta_pt=meta_pt, color=loc_color, italic=True,
            ))

        # Duration
        if c.span_text:
            self._add_meta_run(p, c.span_text, MetaRunConfig(
                brackets=cfg.get("duration_brackets", True),
                open_br="(", close_br=")",
                meta_pt=meta_pt, color=dur_color,
            ))

        return p

    def add_group_title(
        self,
        title: str,
        sec: dict[str, Any] | None = None,
    ):
        """Add a group/category title with optional background."""
        title = (title or "").strip()
        if not title:
            return None

        cfg = sec or {}
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=0)
        self.styles.flush_left(p)

        gt_color = cfg.get("group_title_color")
        gt_bg = cfg.get("group_title_bg") or cfg.get("title_bg")

        r = p.add_run(title)
        r.bold = True

        # Apply background shading
        bg_rgb = self.styles.parse_hex_color(gt_bg)
        if bg_rgb:
            self.styles.apply_shading(p, bg_rgb)
            if not gt_color:
                gt_color = self.styles.auto_contrast_color(bg_rgb)

        # Apply text color
        txt_color = gt_color or cfg.get("item_color") or cfg.get("title_color")
        self.styles.apply_run_color(r, txt_color)

        return p


class ListSectionRenderer:
    """Renders simple list sections (interests, languages, etc.)."""

    def __init__(self, doc, page_cfg: dict[str, Any] | None = None):
        self.doc = doc
        self.bullets = BulletRenderer(doc, page_cfg)
        self.text = TextFormatter()

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
        text = f"{name}{desc_sep}{desc}" if desc else name
        return self.text.clean_inline(text)

    def render_simple_list(
        self,
        items: list[Any],
        sec: dict[str, Any] | None = None,
        *,
        name_keys: tuple = ("name", "title", "label", "text"),
        desc_key: str | None = None,
        desc_sep: str = " — ",
    ) -> list[str]:
        """Normalize and render a simple list section."""
        cfg = sec or {}
        lines = [
            txt for it in items
            if (txt := self._extract_item_text(it, name_keys, desc_key, desc_sep))
        ]

        if lines:
            if cfg.get("bullets", True):
                self.bullets.add_bullets(lines, glyph=self.bullets.resolve_glyph(sec))
            else:
                from .docx_styles import StyleManager
                sep = cfg.get("separator") or " • "
                p = self.doc.add_paragraph(sep.join(lines))
                StyleManager.tight_paragraph(p, after_pt=2)

        return lines
