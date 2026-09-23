"""Rendered-prompt checks: isolated stages never point their agent at the workspace.

An ``isolation: worktree`` agent cannot reach the shared workspace. The engine's
generated sections already send it to ``<your-cwd>/inputs/`` and
``<your-cwd>/outputs/``, but the stage description is embedded verbatim ABOVE
them, and a "read {workspace}/sections.md" there wins. Since #406 renders
``{workspace}`` as an absolute path, that instruction also reads as definitive.
consolidate-schema shipped three of these; no lint rule sees them, because
they are prose. So these tests render every shipped workflow through the engine
and read the Task text an agent actually receives.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.workflow_tests.test_shipped_catalog import (
    REPO_ROOT,
    _catalog_files,
    _is_fragment,
    _load_raw,
    _sample_params,
)
from workflow.compiler import compile_workflow
from workflow.dispatch import build_agent_prompt
from workflow.parser import parse_workflow

_PLACEHOLDER = "{workspace}"

# Headings the engine appends after the description. The Task section is
# everything between "## Task" and the first of these.
_ENGINE_HEADINGS = re.compile(
    r"\n## (?:Fan-out|Workspace|Input Data|CLI Commands|Template|Writing Guide"
    r"|Output Files|Output|Completion)\b"
)

# A workspace mention is an INSTRUCTION when one of these ends the words just
# before it: "design from <ws>", "verify against <ws>", "only under <ws>".
_INSTRUCTION_WORDS = frozenset(
    {"from", "against", "under", "in", "into", "to", "at", "read", "write", "record"}
)
_INSTRUCTION_REACH = 4

# ...unless the clause leading up to it negates it ("NOT from <ws>", "Never
# write to <ws>") or describes the orchestrator's copy-back ("copies ... into
# <ws>"). Only the words BEFORE the mention count: in "write only under <ws>,
# never into tests/" the "never" governs tests/, not the workspace.
_EXEMPTING = re.compile(r"\b(?:not|never|cannot|no|cop(?:y|ies|ied))\b", re.IGNORECASE)
_EXEMPT_REACH = 12

# Mentions that match the instruction shape but were read and found to be
# explanation, not instruction. Keyed by (workflow, stage, text just before
# the mention, in _words form -- punctuation stripped). Do not add to this
# without reading the sentence in the
# rendered prompt: an entry silences that exact sentence and nothing else.
_REVIEWED_EXPLANATIONS = frozenset(
    {
        # Explains why an uncopied report deadlocks; tells the agent nothing.
        ("workflows/code/calendar-plan-symmetry.yaml", "implement-producer",
         "the completion check waits for the report under"),
        # Describes where read-the-seam validated the params upstream.
        ("workflows/demo/qwen-job-type.yaml", "write-handler",
         "validated by read-the-seam's STEP 0 against"),
        # "Writing to a literal <ws> path instead would ..." -- a warning.
        ("workflows/demo/qwen-job-type.yaml", "write-handler",
         "Writing to a literal"),
    }
)


def _task(prompt: str) -> str:
    """The stage description as rendered, or '' for kinds that drop it."""
    if "## Task\n" not in prompt:
        return ""
    return _ENGINE_HEADINGS.split(prompt.split("## Task\n", 1)[1], maxsplit=1)[0]


def _words(text: str) -> list[str]:
    return [w for w in (t.strip("`'\"(),") for t in text.split()) if w]


def _instructions_to_use_workspace(task: str, ws: str) -> list[str]:
    """Text preceding each workspace mention that instructs the agent to use it."""
    tokens = re.compile("|".join(map(re.escape, (_PLACEHOLDER, ws))))
    found = []
    for sentence in re.split(r"(?<=[.;:!?])\s", re.sub(r"\s+", " ", task)):
        for match in tokens.finditer(sentence):
            before = _words(sentence[: match.start()])
            near = {w.lower() for w in before[-_INSTRUCTION_REACH:]}
            if near & _INSTRUCTION_WORDS and not _EXEMPTING.search(
                " ".join(before[-_EXEMPT_REACH:])
            ):
                found.append(" ".join(before[-_EXEMPT_REACH:]))
    return found


def _rendered_catalog() -> list[tuple[str, str, bool, str]]:
    """(workflow, stage, isolated, prompt) for every stage of every workflow."""
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        ws = str(Path(tmp).resolve())
        for path in _catalog_files():
            if _is_fragment(_load_raw(path)):
                continue
            rel = str(path.relative_to(REPO_ROOT))
            defn = parse_workflow(str(path))
            manifest = compile_workflow(defn, project_root=REPO_ROOT,
                                        trigger_params=_sample_params(path, defn))
            for name, stage in manifest.resolved_stages.items():
                agent = stage.spec.agent
                prompt = build_agent_prompt(stage, defn.name, ws)
                rows.append((rel, name, bool(agent and agent.isolation),
                             prompt.replace(ws, _WS_MARK)))
    return rows


# The temp workspace is replaced by a fixed marker so the rows outlive it.
_WS_MARK = "/WORKSPACE-UNDER-TEST"
_ROWS = _rendered_catalog()


class TestIsolatedStagesAvoidWorkspace(unittest.TestCase):
    def test_catalog_was_actually_rendered(self) -> None:
        isolated = {(wf, st) for wf, st, iso, _ in _ROWS if iso}
        # A floor, not a count: an empty render would pass every check below.
        self.assertGreaterEqual(len(isolated), 20)
        for stage in ("impl-schema", "test-schema", "migrate-callsites",
                      "test-e2e-data", "impl-pdf", "test-pdf"):
            self.assertIn(("workflows/resume/consolidate-schema.yaml", stage), isolated)

    def test_no_isolated_task_tells_the_agent_to_use_the_workspace(self) -> None:
        for wf, stage, isolated, prompt in _ROWS:
            if not isolated:
                continue
            with self.subTest(workflow=wf, stage=stage):
                hits = [
                    before for before in _instructions_to_use_workspace(_task(prompt), _WS_MARK)
                    if not any(
                        (wf, stage) == (r_wf, r_stage) and before.endswith(r_text)
                        for r_wf, r_stage, r_text in _REVIEWED_EXPLANATIONS
                    )
                ]
                self.assertEqual(hits, [], msg=(
                    "an isolated stage's description sends its agent to the shared "
                    "workspace, which it cannot reach. Point it at "
                    "<your-cwd>/inputs/<declared path> or <your-cwd>/outputs/<name>."
                ))

    def test_reviewed_explanations_are_not_stale(self) -> None:
        """Each allowlisted sentence must still exist, or the entry is dead weight
        that would silently cover a future instruction with the same prefix."""
        rendered = {(wf, st): _task(p) for wf, st, _, p in _ROWS}
        for wf, stage, text in _REVIEWED_EXPLANATIONS:
            with self.subTest(workflow=wf, stage=stage):
                # Compared in _words form, the same normalisation the match uses.
                self.assertIn(text, " ".join(_words(rendered[(wf, stage)])))


class TestOutputPathsResolve(unittest.TestCase):
    def test_no_output_path_carries_a_literal_workspace_placeholder(self) -> None:
        """writes_to gets no {param} substitution: "{workspace}/x.md" rendered as
        <ws>/outputs/{workspace}/x.md, a directory named with literal braces."""
        for wf, stage, _, prompt in _ROWS:
            with self.subTest(workflow=wf, stage=stage):
                generated = _ENGINE_HEADINGS.split(prompt, maxsplit=1)
                tail = prompt[len(generated[0]):] if len(generated) > 1 else ""
                self.assertNotIn(f"{_WS_MARK}/outputs/{_PLACEHOLDER}", tail)
                self.assertNotIn(f"<your-cwd>/outputs/{_PLACEHOLDER}", tail)


class TestConsolidateSchemaInputs(unittest.TestCase):
    """Each isolated consolidate-schema stage reads its upstream files by own-cwd path."""

    def _task(self, stage: str) -> str:
        for wf, st, _, prompt in _ROWS:
            if (wf, st) == ("workflows/resume/consolidate-schema.yaml", stage):
                return re.sub(r"\s+", " ", _task(prompt))
        self.fail(f"stage {stage} not rendered")

    def test_readers_name_the_copied_in_path(self) -> None:
        cases = {
            "impl-schema": ("schema-design.md", "sections.md"),
            "test-schema": ("sections.md",),
            "migrate-callsites": ("sections.md",),
            "test-e2e-data": ("sections.md",),
        }
        for stage, files in cases.items():
            for name in files:
                with self.subTest(stage=stage, file=name):
                    self.assertIn(f"<your-cwd>/inputs/outputs/{name}", self._task(stage))

    def test_sections_md_readers_declare_its_producer(self) -> None:
        """The orchestrator copies in only what reads_from names, so citing
        sections.md without audit-sections there points at a file never copied."""
        for wf, stage, _, prompt in _ROWS:
            if wf != "workflows/resume/consolidate-schema.yaml" or "## Input Data" not in prompt:
                continue
            if "inputs/outputs/sections.md" in _task(prompt):
                with self.subTest(stage=stage):
                    inputs = prompt.split("## Input Data", 1)[1].split("\n## ", 1)[0]
                    self.assertIn("audit-sections", inputs)

    def test_pii_never_lands_under_a_checkout(self) -> None:
        task = self._task("test-e2e-data")
        self.assertIn("mktemp -d", task)
        self.assertIn('rm -rf "$E2E_TMP"', task)
        self.assertNotIn(f"only under {_WS_MARK}", task)
