"""Enforce the Option C dict/typed boundary through ``src/resume/``.

WHY THIS CHECK EXISTS
=====================

Option C draws a permanent line through the resume package. On one side the
render path consumes a typed schema (``src/resume/schema.py``). On the other
side the filter/scoring modules keep working in raw dicts. The dict side is
DELIBERATE, not leftover work:

    priority.py, skills_filter.py, experience_filter.py,
    overlays.py, aligner.py, summarizer.py

These modules rebuild candidate entries with dict-splat expressions such as::

    e = {**e, "bullets": _filter_items(e["bullets"], cutoff)}

``{**e, ...}`` raises ``TypeError`` when ``e`` is a dataclass instance - a
dataclass is not a mapping, so it cannot be splatted. Typing these interiors
would require rewriting every such rebuild, and the pipeline does not need it:
``FilterPipeline`` converts at its own edges, so the dict interiors are an
implementation detail that never escapes.

The risk this check defends against is a well-intentioned future contributor
deciding to "finish the migration", typing the filters, and shipping silently
wrong output - filters that quietly drop entries, or renders that lose bullets,
with no test failing. That is why the boundary is enforced mechanically rather
than described in a comment. This split was a human-approved design decision,
not an accident of incremental migration. If you are here because this check
failed, the fix is almost never "delete the check".

WHAT IS ENFORCED
================

Rule 1 (strict today): dict-domain modules must not import from ``schema``.
    Already true, so it is enforced with no tolerance.

Rule 2 (ratcheted): typed-domain render modules must not call ``.get()`` on a
    candidate-data receiver.
    This rule runs against a per-module baseline: known sites are tolerated, any
    NEW site fails, and a module that drops below its baseline ALSO fails with
    an instruction to lower the number. Without that downward ratchet a baseline
    silently stops meaning anything as the migration proceeds.

    The render-path migration is now complete, and the nine remaining sites are
    a documented permanent floor rather than outstanding work: they read the two
    structures the schema deliberately leaves untyped -- the ``teaching`` section
    (``list[Any]``) and the nested ``contact`` mapping. See the per-entry notes
    on UNMIGRATED_GET_BASELINE. The table stays because it still catches NEW
    dict reads; it can be deleted only if those two structures are ever typed.

Rule 2 keys on the receiver NAME, not the file: the render modules read their
own configuration as dicts forever, and config reads sit on lines adjacent to
candidate-data reads. See ``receivers.py`` for the classification and how it
was derived.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from .receivers import (
    AMBIGUOUS_RECEIVERS,
    CANDIDATE_DATA_RECEIVERS,
    CONFIG_RECEIVERS,
)

RESUME_SRC = Path(__file__).resolve().parents[3] / "src" / "resume"

# Modules that stay dict-based permanently. They must not import the schema.
DICT_DOMAIN_MODULES: tuple[str, ...] = (
    "priority.py",
    "skills_filter.py",
    "experience_filter.py",
    "overlays.py",
    "aligner.py",
    "summarizer.py",
)

# Render modules that consume the typed schema once Steps 3-5 land.
TYPED_DOMAIN_MODULES: tuple[str, ...] = (
    "docx_base.py",
    "docx_renderers.py",
    "docx_sections_exp.py",
    "docx_sections_simple.py",
    "docx_sections_skills.py",
    "docx_sidebar_cells.py",
    "docx_sidebar_sections.py",
    "docx_standard.py",
    "docx_writer.py",
)

# Per-module count of un-migrated candidate-data `.get()` calls.
#
# This is a RATCHET, not a permanent allowance. Migrating a module means
# lowering its number here; the check fails if the real count drifts either
# way. Target state is every entry at 0, at which point delete this table and
# the tolerance logic with it.
UNMIGRATED_GET_BASELINE: dict[str, int] = {
    # The single remaining site is the ``contact.get()`` read in
    # ``get_contact_field``. ``Resume.contact`` is a nested mapping the schema
    # deliberately does NOT model field-by-field (it stays
    # ``dict[str, Any] | None``), so this is a permanent floor, not
    # un-migrated work. from_dict already promotes contact values onto the
    # top-level scalars; this read is the fallback for a Resume built
    # directly, bypassing that promotion.
    #
    # Was 4: _identity_fields inlined the same fallback per field and
    # _get_contact_field duplicated it a third time. Consolidating them onto
    # one helper collapsed four reads into one.
    "docx_base.py": 1,
    # Three of these are the ``it.get()`` calls in _extract_item_text's dict
    # branch, which serves the deliberately-untyped ``teaching`` section
    # (schema-design.md §1). The fourth is the ``extra.get()`` in _item_name,
    # which recovers an alias spelling the schema filed in ``_Item.extra``
    # because it is not a modelled field. Neither is un-migrated work: the
    # first will not reach 0 while ``teaching`` stays ``list[Any]``, and the
    # second has no attribute to migrate to by construction.
    "docx_renderers.py": 4,
    "docx_sections_exp.py": 0,
    "docx_sections_simple.py": 0,
    "docx_sections_skills.py": 0,
    "docx_sidebar_cells.py": 0,
    # The single remaining site is the ``item.get()`` in _render_main_teaching,
    # which serves the same deliberately-untyped ``teaching`` section as the
    # docx_renderers.py entry above. Not un-migrated work; will not reach 0
    # while ``teaching`` stays ``list[Any]``.
    "docx_sidebar_sections.py": 1,
    "docx_standard.py": 0,
    # Was 1: _get_contact_field's ``contact.get()`` fallback. It now delegates
    # to docx_base.get_contact_field, so the read lives at that single site.
    "docx_writer.py": 0,
}


@dataclass(frozen=True)
class GetCall:
    """A single ``.get()`` call site found in a render module."""

    module: str
    lineno: int
    receiver: str

    def describe(self) -> str:
        return f"{self.module}:{self.lineno}: {self.receiver}.get(...)"


def _receiver_name(node: ast.expr) -> str | None:
    """Return the receiver name for a ``.get()`` call, or None if not a name.

    Matches on the final attribute segment so ``data`` and ``self.data``
    classify identically. Call and subscript receivers (``(x or {}).get()``,
    ``xs[0].get()``) have no stable name and are skipped: they are config reads
    in practice, and inventing a name for them would be a guess.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _scan_get_calls(path: Path) -> list[GetCall]:
    """Collect every ``.get()`` call in a module with its receiver name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[GetCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        receiver = _receiver_name(func.value)
        if receiver is None:
            continue
        found.append(GetCall(path.name, node.lineno, receiver))
    return found


def _imports_schema(path: Path) -> list[int]:
    """Return line numbers of any import that pulls in ``resume.schema``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Covers `from .schema import X` and `from resume.schema import X`.
            if node.module and node.module.split(".")[-1] == "schema":
                hits.append(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == "schema":
                    hits.append(node.lineno)
    return hits


class DictDomainImportBoundaryTest(unittest.TestCase):
    """Rule 1: dict-domain modules must not import the typed schema."""

    def test_dict_domain_modules_do_not_import_schema(self) -> None:
        violations: list[str] = []
        for module in DICT_DOMAIN_MODULES:
            path = RESUME_SRC / module
            self.assertTrue(path.exists(), f"missing dict-domain module: {path}")
            for lineno in _imports_schema(path):
                violations.append(f"  {module}:{lineno}: imports resume.schema")

        self.assertEqual(
            [],
            violations,
            "\n\nBOUNDARY VIOLATION - dict-domain module imports the typed schema.\n"
            + "\n".join(violations)
            + "\n\nThese modules are dict-based BY DESIGN and must stay that way.\n"
            "They rebuild entries with `{**e, ...}`, which raises TypeError on a\n"
            "dataclass. FilterPipeline converts at its own edges instead.\n"
            "If you are typing these interiors, stop: that change ships silently\n"
            "wrong filter output. See this module's docstring for the rationale.\n",
        )


class TypedDomainGetBoundaryTest(unittest.TestCase):
    """Rule 2: render modules must not ``.get()`` on candidate data (ratcheted)."""

    def _candidate_data_calls(self, module: str) -> list[GetCall]:
        path = RESUME_SRC / module
        self.assertTrue(path.exists(), f"missing typed-domain module: {path}")
        return [
            call
            for call in _scan_get_calls(path)
            if call.receiver in CANDIDATE_DATA_RECEIVERS
        ]

    def test_every_receiver_is_classified(self) -> None:
        """Fail loudly on a receiver nobody has classified yet.

        An unknown receiver must never default to "config" - that would let a
        newly introduced candidate-data name slip past Rule 2 unnoticed. New
        names have to be classified in receivers.py deliberately.
        """
        unknown: dict[str, list[str]] = {}
        for module in TYPED_DOMAIN_MODULES:
            for call in _scan_get_calls(RESUME_SRC / module):
                known = (
                    call.receiver in CANDIDATE_DATA_RECEIVERS
                    or call.receiver in CONFIG_RECEIVERS
                    or call.receiver in AMBIGUOUS_RECEIVERS
                )
                if not known:
                    unknown.setdefault(call.receiver, []).append(call.describe())

        detail = "\n".join(
            f"  {receiver}:\n" + "\n".join(f"    {s}" for s in sites)
            for receiver, sites in sorted(unknown.items())
        )
        self.assertEqual(
            {},
            unknown,
            "\n\nUNCLASSIFIED `.get()` receiver(s) in the render path.\n"
            f"{detail}\n\n"
            "Classify each one in tests/resume_tests/boundary/receivers.py:\n"
            "  - CANDIDATE_DATA_RECEIVERS if it holds resume content (must migrate)\n"
            "  - CONFIG_RECEIVERS if it holds template/page/layout config (stays a dict)\n"
            "  - AMBIGUOUS_RECEIVERS if the kind depends on the call site\n"
            "Do not guess. A candidate-data name filed as config disables this\n"
            "check for that name and gives false confidence.\n",
        )

    def test_no_new_candidate_data_get_calls(self) -> None:
        """New candidate-data ``.get()`` sites above the baseline fail."""
        regressions: list[str] = []
        for module in TYPED_DOMAIN_MODULES:
            calls = self._candidate_data_calls(module)
            allowed = UNMIGRATED_GET_BASELINE.get(module, 0)
            if len(calls) > allowed:
                listing = "\n".join(f"    {c.describe()}" for c in calls)
                regressions.append(
                    f"  {module}: {len(calls)} candidate-data .get() calls,"
                    f" baseline allows {allowed}\n{listing}"
                )

        self.assertEqual(
            [],
            regressions,
            "\n\nBOUNDARY VIOLATION - new `.get()` on candidate data in the render path.\n"
            + "\n".join(regressions)
            + "\n\nRender modules read candidate data off the typed schema, so use\n"
            "attribute access (`entry.title`) instead of `.get(\"title\")`.\n"
            "Config receivers (page_cfg, template, cfg, ...) stay dicts and are\n"
            "not flagged - if you believe this receiver is config, classify it in\n"
            "tests/resume_tests/boundary/receivers.py rather than raising the\n"
            "baseline. Raising the baseline is only correct if you deliberately\n"
            "added un-migrated code, which Steps 3-5 should not be doing.\n",
        )

    def test_baseline_ratchets_downward(self) -> None:
        """A module that drops below its baseline must update the baseline.

        Without this, migrating a module leaves a stale allowance behind, and
        the baseline stops describing reality - at which point a later
        regression can reoccupy the slack without failing anything.
        """
        stale: list[str] = []
        for module in TYPED_DOMAIN_MODULES:
            actual = len(self._candidate_data_calls(module))
            allowed = UNMIGRATED_GET_BASELINE.get(module, 0)
            if actual < allowed:
                stale.append(f"  {module}: baseline {allowed} -> actual {actual}")

        self.assertEqual(
            [],
            stale,
            "\n\nGOOD NEWS - migration progressed; the baseline is now stale.\n"
            + "\n".join(stale)
            + "\n\nLower these numbers in UNMIGRATED_GET_BASELINE"
            " (tests/resume_tests/boundary/test_schema_boundary.py)\n"
            "to the actual counts shown above. This is a ratchet: it only ever\n"
            "goes down. When every entry reaches 0, delete the table and the\n"
            "tolerance logic - the rule is then fully strict.\n",
        )


if __name__ == "__main__":
    unittest.main()
