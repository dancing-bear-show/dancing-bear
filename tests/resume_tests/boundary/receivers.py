"""Receiver classification for the resume dict/typed boundary check.

The boundary check keys on the RECEIVER NAME of a ``.get()`` call, not on the
file it appears in. A blanket "no ``.get(`` inside ``docx_*``" rule would be
wrong: the render modules legitimately read their *render configuration* as
dicts forever (template YAML, page/layout config), and only *candidate data*
moves to the typed schema. Both kinds of receiver appear on adjacent lines of
the same function, so file-level rules cannot separate them.

The lists below were derived by walking the AST of all nine typed-domain render
modules and classifying every distinct receiver found (244 ``.get()`` calls),
not from a sample. Each name is grouped with the reason it lands where it does.

Receivers are matched on the FINAL attribute segment, so ``data`` and
``self.data`` classify identically, as do ``page_cfg`` and ``self.page_cfg``.
"""

from __future__ import annotations

# Candidate data: the resume content itself. These receivers hold the payload
# that Option C moves onto the typed schema, so every ``.get()`` on one of them
# is a site that Steps 3-5 must convert to attribute access.
CANDIDATE_DATA_RECEIVERS: frozenset[str] = frozenset(
    {
        # The candidate payload and its nested contact block.
        "data",  # the resume dict itself
        "candidate",
        "contact",  # always `data.get("contact")` - nested candidate data
        # Experience entries and their bullets.
        "e",  # experience entry
        "exp",  # experience entry
        "entry",
        "b",  # a bullet (dict-or-str shape)
        # Education entries.
        "edu",
        "ed",
        # Skills groups and their items.
        "g",  # skills group
        "group",  # skills group
        "item",  # skill/award/cert item
        "it",  # skill/award/cert item
        # Presentations and summary content.
        "pres",
        "summary",
    }
)

# Render configuration: template YAML, page/layout styling, and scoring inputs.
# These stay dicts permanently. They are not candidate data and must NOT be
# flagged - doing so would make the check unimplementable, since roughly half
# of every render module's `.get()` calls are config reads.
CONFIG_RECEIVERS: frozenset[str] = frozenset(
    {
        # Template and section configuration.
        "template",
        "sec",  # a template section config block
        "structure",  # section order/title override
        "tpl_by_key",  # section-config lookup table
        "key_to_title",  # section-title lookup table
        "spec",
        # Page and layout styling.
        "cfg",
        "page_cfg",
        "layout_cfg",
        "style_profile",
        "bul",  # bullet *style* config (glyph/style)
        "bulp",  # bullet *style* config (glyph/style)
        # Tailoring/scoring inputs, not candidate content.
        "seed",  # keyword seed config
        "kws",
        "keyword_spec",
        "alignment",
        "al",
        "job_cfg",
        "scores",
        # Module-level dispatch/lookup constants.
        "SECTION_RENDERERS",
        "_MAIN_SECTION_RENDERERS",
        "_SECTION_DATA_KEYS",
    }
)

# Receivers whose kind depends on the call site rather than the name.
#
# ``s`` is the real case: in ``docx_writer._resolve_sections`` it iterates
# template *sections* (config), while in
# ``docx_sidebar_sections._normalize_summary_items`` it iterates *summary*
# items (candidate data). A name-keyed classifier cannot tell these apart, and
# guessing either way would produce a silently wrong result - a false pass on
# the summary sites, or unfixable false failures on the section sites.
#
# These are reported by the check as "unclassified" rather than counted as
# violations or silently ignored. The migration should rename them at the call
# site (``sec`` for config, ``summary_item`` for candidate data), which removes
# the ambiguity instead of encoding a guess here.
AMBIGUOUS_RECEIVERS: frozenset[str] = frozenset({"s"})
