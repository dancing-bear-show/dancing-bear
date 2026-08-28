"""Skills, summary, and technologies section renderers for DOCX resume output.

Provides:
  - SummarySectionRenderer: summary/profile section (string or list)
  - SkillsSectionRenderer: skills with groups or flat list
  - TechnologiesSectionRenderer: technologies (extends SkillsSectionRenderer)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .docx_renderers import HeaderRenderer, ListSectionRenderer
from .schema import PriorityItem, Resume, SkillGroup, SkillGroupItem


#: Fallback separator printed between a skills/technologies item's name and its
#: description when a template enables ``show_desc`` without setting
#: ``desc_separator``. There is exactly one such fallback, deliberately: the
#: skills bullet path and the technologies path each used to carry their own
#: (" -- " and ": " respectively), so the same config shape rendered differently
#: depending on which renderer and which branch happened to handle it. Every
#: shipped template sets ``desc_separator: ": "`` explicitly, so this value
#: matches what they already produce.
DEFAULT_DESC_SEPARATOR = ": "


def _resolve_desc_separator(cfg: dict) -> str:
    """Read ``desc_separator`` from a section config, or fall back.

    THE ONLY READER of ``desc_separator``. Every renderer resolves the
    separator through here so no caller can introduce a second, disagreeing
    default -- which is exactly how the skills path once ended up joining on
    " -- " and re-splitting on ": ".
    """
    return str(cfg.get("desc_separator") or DEFAULT_DESC_SEPARATOR)


def _safe_int_limit(cfg: dict, key: str) -> int:
    """Read an int limit from config, falling back to 0 (no limit) on bad values."""
    try:
        return int(cfg.get(key, 0) or 0)
    except Exception:  # nosec B110 - invalid config value; fall back to no limit
        return 0


@dataclass(frozen=True)
class LabeledItem:
    """One skills entry with its name and description still separable.

    WHY THIS EXISTS
        The renderer needs to bold the name half of a skill bullet and leave
        the separator and description plain, which means it needs to know
        where the name ends. That boundary is known exactly at normalization
        time -- ``SkillGroupItem`` carries ``name`` and ``desc`` as distinct
        fields -- and was previously destroyed by flattening both into one
        string, then guessed back by splitting that string on the separator.

        The guess did not work. ``_render_groups`` joined with a
        ``desc_separator`` defaulting to " -- " while ``_render_bullet_items``
        re-split on one defaulting to ": ", so with no explicit config the
        split never matched and every item rendered as a single plain run.
        Worse, splitting is ambiguous whenever a description itself contains
        the separator.

        Carrying the parts through instead makes the boundary exact. The
        separator travels with them (see ``sep``) and every reader of
        ``desc_separator`` now goes through ``_resolve_desc_separator``, so
        two defaults can no longer disagree in the first place.

    ``text`` is the flattened form, preserved verbatim so callers that only
    want a string (the technologies collector, the non-bullet joined form)
    read the same value they always did.

    ``sep`` is the separator this item was normalized with, carried alongside
    the halves so the renderer prints the same one that went into ``text``
    instead of re-deriving it from config. Re-deriving is what allowed the
    bulleted and joined forms of the same config to disagree.
    """

    name: str
    desc: str
    text: str
    sep: str = DEFAULT_DESC_SEPARATOR

    @property
    def has_desc(self) -> bool:
        """Whether a description was present and requested for display."""
        return bool(self.desc)


def _labeled_item(item: Any, show_desc: bool, desc_sep: str) -> LabeledItem:
    """Split a skills item into its name and description halves.

    ``SkillGroupItem`` resolves ``name|title|label`` onto ``name`` and
    ``desc|description`` onto ``desc`` at from_dict time, so both are read
    from the canonical field rather than searched for here.

    Non-schema values (a bare string that never went through the schema, a
    number) are stringified into ``name`` with no description, matching the
    previous scalar branch.
    """
    if not isinstance(item, SkillGroupItem):
        text = str(item)
        return LabeledItem(name=text, desc="", text=text, sep=desc_sep)

    name = item.name.strip()
    desc = item.desc.strip() if (item.desc and show_desc) else ""
    text = f"{name}{desc_sep}{desc}" if desc else name
    return LabeledItem(name=name, desc=desc, text=text, sep=desc_sep)


class SummarySectionRenderer(ListSectionRenderer):
    """Renders summary/profile section."""

    def render(
        self,
        resume: Resume,
        sec: dict | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        """Render the summary as prose or as bullets.

        Which branch runs is NOT a formatting preference: the prose branch
        keeps the text verbatim while the bullet branch strips the terminal
        period, so routing a summary to the wrong one silently rewrites it.

        A summary that arrived as a bare string takes the prose branch, and
        ``summary_is_scalar`` is the only thing that can still tell it apart --
        normalization stores a scalar and a genuine one-item list identically.
        Everything else takes the bullet branch, falling back to ``headline``
        when there is no summary text at all.
        """
        cfg = sec or {}

        if resume.summary_is_scalar:
            # A scalar summary is prose, or -- when the string was empty --
            # falls through to the headline exactly as `summary or headline`
            # did, because an empty string is falsy on that read.
            text = resume.summary[0].text or resume.headline
            if text.strip():
                self._render_string_summary(text, cfg, keywords)
            return

        if resume.summary:
            # A present-but-all-blank list renders nothing and does NOT fall
            # through to the headline: `summary or headline` saw a non-empty
            # list, so the headline was never reached.
            self._render_bullet_summary(resume.summary, sec, keywords)
            return

        if resume.headline.strip():
            self._render_string_summary(resume.headline, cfg, keywords)

    def _render_bullet_summary(
        self,
        summary: list[PriorityItem],
        sec: dict | None,
        keywords: list[str] | None,
    ) -> None:
        """Render summary items as bullets, skipping blank ones."""
        items = self._normalize_list_items(summary)
        if not items:
            return
        norm_items = [self.text.normalize_bullet(it) for it in items]
        self.bullets.add_bullets(
            norm_items, keywords=keywords, glyph=self.bullets.resolve_glyph(sec)
        )

    def _normalize_list_items(self, summary: list[PriorityItem]) -> list[str]:
        """Extract the display text from each summary item, dropping empties.

        ``desc`` is a real fallback, not a leftover: it is a declared field on
        ``PriorityItem`` distinct from ``text``, so a ``{"desc": ...}`` item
        carries its content there and would otherwise render as nothing. The
        ``line`` spelling needs no branch -- the schema aliases it onto
        ``text`` at from_dict time.
        """
        items: list[str] = []
        for it in summary:
            s = str(it.text or it.desc or "").strip()
            if s:
                items.append(s)
        return items

    def _render_string_summary(
        self,
        text: str,
        cfg: dict,
        keywords: list[str] | None,
    ) -> None:
        """Render a string summary (optionally as bullets)."""
        if cfg.get("bulleted"):
            self._render_bulleted_string(text, cfg, keywords)
        else:
            p = self.doc.add_paragraph()
            self.bullets.styles.tight_paragraph(p, after_pt=2)
            # Prose summaries are candidate content, so they honour inline
            # markup exactly as the bulleted branch does. Routing through the
            # shared helper is what keeps the two branches in step -- this one
            # used to call _bold_keywords directly and would otherwise have
            # been the one summary shape that printed "**" literally.
            self.bullets._add_text_with_optional_keywords(p, text, keywords)

    def _render_bulleted_string(
        self,
        text: str,
        cfg: dict,
        keywords: list[str] | None,
    ) -> None:
        """Split a string summary into bullets.

        Newlines win when present: the docx parser joins each source profile
        bullet with "\\n", so those are the real item boundaries. Splitting such
        a summary on "." instead would break every bullet containing an
        abbreviation, a version number, or a trailing period. Sentence
        splitting remains the fallback for single-line summaries.
        """
        if "\n" in text:
            items = [s.strip() for s in text.split("\n") if s.strip()]
        else:
            items = [s.strip() for s in text.split(".") if s.strip()]
        max_sent = _safe_int_limit(cfg, "max_sentences")
        if max_sent > 0:
            items = items[:max_sent]
        norm_items = [self.text.normalize_bullet(it) for it in items]
        self.bullets.add_bullets(
            norm_items, keywords=keywords, glyph=self.bullets.resolve_glyph(cfg)
        )


class SkillsSectionRenderer(ListSectionRenderer):
    """Renders skills section with groups or flat list."""

    def __init__(self, doc: Any, page_cfg: dict | None = None) -> None:
        super().__init__(doc, page_cfg)
        self.headers = HeaderRenderer(doc)

    def render(
        self,
        resume: Resume,
        sec: dict | None = None,
    ) -> None:
        # `skills` is deliberately untyped (list[str]), so its entries are
        # stringified rather than read as schema items.
        skills = [self.text.clean_inline(str(s)) for s in resume.skills]
        cfg = sec or {}

        if resume.skills_groups:
            self._render_groups(resume.skills_groups, cfg)
        elif skills:
            self._render_flat_skills(skills, cfg)

    def _render_groups(self, groups: list[SkillGroup], cfg: dict) -> None:
        """Render skills organized by groups."""
        as_bullets = bool(cfg.get("bullets", False))
        sep = cfg.get("separator") or " • "
        max_groups = int(cfg.get("max_groups", 999))
        max_items_per_group = int(cfg.get("max_items_per_group", 999))
        show_desc = bool(cfg.get("show_desc", True))
        desc_sep = _resolve_desc_separator(cfg)

        for g in groups[:max_groups]:
            # `title` only -- SkillGroup declares no aliases, so a group keyed
            # by `name` or `label` has an empty title and renders untitled.
            # That is the pre-migration behaviour and the goldens pin it.
            title = str(g.title or "").strip()
            items = self._normalize_group_items(g.items, show_desc, desc_sep)[:max_items_per_group]

            if not items:
                continue

            if as_bullets:
                if title:
                    self.headers.add_group_title(title, cfg)
                self._render_bullet_items(items, cfg)
            else:
                self._render_inline_items(title, items, cfg, sep)

    def _normalize_group_items(
        self, raw_items: list[SkillGroupItem], show_desc: bool, desc_sep: str
    ) -> list[LabeledItem]:
        """Normalize items from a skills group, dropping ones that render empty.

        ``clean_inline`` is applied to each half rather than to the joined
        string so the name/desc boundary survives normalization. The renderer
        bolds the name half, so flattening the two together here and splitting
        them back apart later is what previously lost that boundary.

        An item with no recognised name key (``name|title|label``) and no
        ``desc`` normalizes to "". Kept in the list it reaches the renderers as
        a textless bullet -- a bare glyph on a line of its own. Both branches
        of ``_render_groups`` emit that glyph, so dropping the item here covers
        them at their one shared chokepoint, and matches what
        ``_normalize_group_tech_items`` already does on the technologies path.

        The drop has to happen *here* rather than in the caller: a
        ``LabeledItem`` is a dataclass and therefore always truthy, so an empty
        one would survive the caller's ``if not items`` guard.

        The test is the *normalized* text, so an item that resolves to content
        through an alias, or one carrying only ``desc``, still renders.
        """
        normalized: list[LabeledItem] = []
        for x in raw_items:
            item = _labeled_item(x, show_desc, desc_sep)
            name = self.text.clean_inline(item.name)
            desc = self.text.clean_inline(item.desc)
            if not name and not desc:
                continue
            text = f"{name}{desc_sep}{desc}" if desc else name
            normalized.append(LabeledItem(name=name, desc=desc, text=text, sep=desc_sep))
        return normalized

    def _render_bullet_items(self, items: list[LabeledItem], cfg: dict) -> None:
        """Render items as bullets, bolding the name half when one is present.

        Both branches emit the same kind of paragraph -- they differ only in
        run formatting, not in bullet mechanism. ``add_named_bullet`` and
        ``add_bullet_line`` both build on ``new_bullet_paragraph``.

        An item with a name but no description takes the plain branch, which
        emits the bold name via ``add_named_bullet`` with nothing after it --
        no dangling separator.

        The separator comes off ``it.sep`` -- the one the item was actually
        normalized with -- rather than being re-read from ``cfg`` here. Reading
        it again would reintroduce the very split this carries: this method
        serves both the skills path and the technologies path, which resolved
        ``desc_separator`` against different defaults, so a config that set
        ``show_desc`` without ``desc_separator`` rendered a bulleted item with
        one separator and the joined ``text`` of the same item with another.
        """
        glyph = self.bullets.resolve_glyph(cfg)

        for it in items:
            if not it.name:
                # Description with no name: nothing to bold, and emitting an
                # empty bold run followed by a separator would print a leading
                # separator. Render the description as a plain bullet.
                self.bullets.add_bullet_line(it.desc, glyph=glyph)
            elif it.has_desc:
                self.bullets.add_named_bullet(
                    it.name, it.desc, sec=cfg, glyph=glyph, sep=it.sep
                )
            else:
                self.bullets.add_named_bullet(it.name, "", sec=cfg, glyph=glyph, sep="")

    def _render_inline_items(
        self, title: str, items: list[LabeledItem], cfg: dict, sep: str
    ) -> None:
        """Render a skills group as a title line plus one paragraph per item.

        Despite the name this is the *non-bullet* branch -- the one taken when
        a section config omits ``bullets``. It used to join every item of a
        group into a single paragraph with ``sep`` (default " • ") between
        them, which put the bullet glyph *inside* the text: a seven-group
        resume produced seven paragraphs of ~530 characters each, five glyphs
        buried in every one. Word has no line break to work with there, so it
        wrapped the whole thing as prose and no item was visually separable.

        Items now get one paragraph each, prefixed with the configured bullet
        glyph from ``resolve_glyph`` (default "•"), and the group title
        keeps its own unprefixed line. That matches the reference resume this
        output is styled after, which uses ``Normal`` paragraphs with a literal
        glyph and never nests a glyph inside a paragraph.

        Items are already filtered by ``_normalize_group_items``, so nothing
        reaching here normalizes to empty; an empty one would otherwise render
        as a bare glyph on a line of its own.

        Those per-item paragraphs used to be built here by hand, which is how
        this section ended up at a different left edge from every other one:
        the hand-rolled version set spacing but never reset the indent, so its
        paragraphs carried ``left_indent=None`` while every other bulleted line
        in the document carried ``left_indent=0``. They now go through
        ``add_bullet_line`` like everything else.

        ``sep`` is intentionally no longer used to join: it was only ever a
        visual separator for the collapsed form. It stays in the signature
        because the caller reads it from config and the surrounding branch
        still passes it.

        The group title is emitted bold and the item names are emitted bold
        with their descriptions plain, matching the reference document this
        output is styled after. Items go through ``_render_bullet_items``, the
        same helper the bulleted branch uses, so the two branches cannot drift
        apart in weighting.

        The title is still built here rather than delegated to
        ``add_group_title``. That helper also applies ``flush_left`` and
        config-driven background shading, which would move this paragraph's
        indentation and not merely its weight -- a formatting change beyond
        bolding. Only the bold run is added; spacing and indentation are left
        exactly as they were.
        """
        if title:
            tp = self.doc.add_paragraph()
            self.bullets.styles.tight_paragraph(tp, after_pt=0)
            tp.add_run(title).bold = True

        self._render_bullet_items(items, cfg)

    def _render_bullets_or_joined(self, items: list[str], cfg: dict, sep: str) -> None:
        """Render plain string items as bullets, or as one sep-joined paragraph.

        These items are bare strings that never carried a name/description
        split -- ``resume.skills`` is deliberately untyped -- so there is no
        name half to bold and they stay plain. Bolding the whole of every flat
        skill would be a weighting change this data cannot justify.
        """
        if bool(cfg.get("bullets", False)):
            glyph = self.bullets.resolve_glyph(cfg)
            for it in items:
                self.bullets.add_bullet_line(it, glyph=glyph)
        else:
            self.bullets.add_joined_paragraph(items, sep)

    def _render_flat_skills(self, skills: list[str], cfg: dict) -> None:
        """Render a flat list of skills."""
        sep = cfg.get("separator") or " • "
        max_items = int(cfg.get("max_items", 999))
        self._render_bullets_or_joined(skills[:max_items], cfg, sep)


class TechnologiesSectionRenderer(SkillsSectionRenderer):
    """Renders technologies section (similar to skills)."""

    def render(self, resume: Resume, sec: dict | None = None) -> None:
        tech_items = self._collect_tech_items(resume, sec)
        if not tech_items:
            return

        cfg = sec or {}
        max_items = _safe_int_limit(cfg, "max_items")
        if max_items > 0:
            tech_items = tech_items[:max_items]

        sep = cfg.get("separator") or " • "
        if bool(cfg.get("bullets", True)):
            self._render_bullet_items(tech_items, cfg)
        else:
            self.bullets.add_joined_paragraph([it.text for it in tech_items], sep)

    def _collect_tech_items(
        self, resume: Resume, sec: dict | None
    ) -> list[LabeledItem]:
        """Collect technology items from data sources."""
        cfg = sec or {}
        desc_sep = _resolve_desc_separator(cfg)
        show_desc = bool(cfg.get("show_desc", False))
        tech_items: list[LabeledItem] = []

        for t in resume.technologies:
            item = self._normalize_tech_item(t, show_desc, desc_sep)
            # Explicit None check: a LabeledItem is a dataclass and therefore
            # always truthy, so `if item:` would keep the empties this drops.
            if item is not None:
                tech_items.append(item)

        if not tech_items:
            tech_items = self._extract_from_skills_groups(resume, show_desc, desc_sep)

        return tech_items

    def _normalize_tech_item(
        self, t: Any, show_desc: bool, desc_sep: str
    ) -> LabeledItem | None:
        """Normalize a single technology item, keeping name and desc separable.

        A schema item that yields no text is dropped; a non-schema scalar is
        kept even when it stringifies to something empty-looking, which is what
        the dict/scalar split did before the migration.

        Each half is cleaned independently so the name/desc boundary survives,
        for the same reason as ``_normalize_group_items``.
        """
        item = _labeled_item(t, show_desc, desc_sep)
        if isinstance(t, SkillGroupItem) and not item.text:
            return None

        name = self.text.clean_inline(item.name)
        desc = self.text.clean_inline(item.desc)
        text = f"{name}{desc_sep}{desc}" if desc else name
        return LabeledItem(name=name, desc=desc, text=text, sep=desc_sep)

    def _normalize_group_tech_items(
        self, raw_items: list[SkillGroupItem], show_desc: bool, desc_sep: str
    ) -> list[LabeledItem]:
        """Normalize every item in a single skills group, dropping empties."""
        items: list[LabeledItem] = []
        for x in raw_items:
            item = self._normalize_tech_item(x, show_desc, desc_sep)
            # `is not None` rather than truthiness: see _collect_tech_items.
            if item is not None and item.text:
                items.append(item)
        return items

    def _extract_from_skills_groups(
        self, resume: Resume, show_desc: bool, desc_sep: str
    ) -> list[LabeledItem]:
        """Extract tech items from skills_groups with technology titles."""
        tech_titles = {"technology", "technologies", "tooling", "tools"}

        for g in resume.skills_groups:
            title = str(g.title or "").strip().lower()
            if title in tech_titles:
                return self._normalize_group_tech_items(g.items, show_desc, desc_sep)

        return []
