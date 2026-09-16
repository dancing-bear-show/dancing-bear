"""Bullet rendering for resume DOCX output.

Provides BulletRenderer and the NORMAL_PARAGRAPH_STYLE constant used by all
bulleted sections in the standard layout.
"""
from __future__ import annotations

import logging
from typing import Any

from .docx_styles import StyleManager, TextFormatter
from .inline_markup import (
    MarkupSpan,
    has_inline_markup,
    parse_inline_markup,
    strip_inline_markup,
)

_logger = logging.getLogger(__name__)

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
        """Add text to a paragraph, honouring inline markup and keyword matches.

        THIS IS THE SINGLE RUN-EMITTING PATH for candidate prose. Inline
        ``**bold**``/``*italic*`` markup is resolved first, then each resulting
        span is handed to the keyword pass, so the two features compose instead
        of competing. See ``_add_span`` for how they interact.

        Section titles, names, dates and contact fields do NOT come through
        here -- they are template-supplied chrome, and markup in them would be
        the template's own punctuation rather than something an author wrote.
        """
        for span in parse_inline_markup(text):
            self._add_span(p, span, keywords)

    def _add_span(self, p, span: MarkupSpan, keywords: list[str] | None) -> None:
        """Emit one markup span, applying keyword bolding inside it.

        HOW MARKUP AND KEYWORD BOLDING INTERACT

        Markup wins the outer structure; keyword bolding only ever refines what
        is inside a span. The two cannot double-wrap, because bold is a boolean
        on a run, not a nesting wrapper -- a keyword found inside a ``**bold**``
        span is already bold and setting the flag again is a no-op.

        A span that is ALREADY BOLD therefore skips the keyword pass entirely
        and emits as one run. Running it would split an author-bolded phrase
        into three runs (pre / keyword / post) that all carry ``bold=True`` and
        render identically -- churn with no visual effect, and it would destroy
        the span's italic flag on the two runs the keyword pass rebuilds.

        A span that is italic or plain DOES take the keyword pass, and every
        run it produces inherits the span's italic flag. That is what lets a
        keyword inside ``*italic*`` come out bold-and-italic rather than
        losing its emphasis.
        """
        if not span.text:
            return
        if keywords and not span.bold:
            start = len(p.runs)
            self._bold_keywords(p, span.text, keywords)
            if span.italic:
                for run in p.runs[start:]:
                    run.italic = True
            return
        run = p.add_run(span.text)
        if span.bold:
            run.bold = True
        if span.italic:
            run.italic = True

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

        # The name half is bold by construction, so its own markup would be
        # invisible; strip the delimiters rather than print them literally.
        r_name = p.add_run(strip_inline_markup(name))
        r_name.bold = True
        self.styles.apply_run_color(r_name, name_color)

        if desc:
            if sep:
                p.add_run(sep)
            # The description half is candidate prose and honours markup.
            self._add_text_with_optional_keywords(p, desc, None)
        return p

    def add_joined_paragraph(self, items: list[str], sep: str, *, after_pt: int = 2):
        """Render items as one separator-joined paragraph, honouring markup.

        This is the non-bullet form the skills and technologies sections take
        when their config sets ``bullets: false``. (The simple-list sections no
        longer offer it -- ``render_simple_list`` always bullets and warns on
        the key.) It used to build the paragraph from a single pre-joined
        string (``add_paragraph(sep.join(items))``), which produces one
        undifferentiated run -- so inline markup in an item would have printed
        its delimiters literally in exactly the sections that opted out of
        bullets.

        UNMARKED INPUT KEEPS THE OLD SINGLE-RUN SHAPE. Splitting every joined
        paragraph into per-item runs would rewrite the run structure of every
        existing document that uses this branch: the text is identical, but
        ``word/document.xml`` is not, and the render goldens compare bytes.
        Emphasis needs separate runs; text without emphasis does not, so the
        split is paid for only when some item actually carries markup.
        """
        p = self.doc.add_paragraph()
        self.styles.tight_paragraph(p, after_pt=after_pt)
        if not any(has_inline_markup(item) for item in items):
            p.add_run(sep.join(items))
            return p
        for i, item in enumerate(items):
            if i:
                p.add_run(sep)
            self._add_text_with_optional_keywords(p, item, None)
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
