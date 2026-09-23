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
        <ws>/outputs/{workspace}/x.md, a directory named with literal braces. The
        placeholder can land anywhere in a path (<ws>/outputs/design/{workspace}.md,
        <ws>/validation/{workspace}.json), so no prefix list is complete. The
        engine-generated sections never legitimately carry the token at all, so
        assert it is absent from them outright."""
        path_token = re.compile(r"\S*" + re.escape(_PLACEHOLDER) + r"\S*")
        for wf, stage, _, prompt in _ROWS:
            with self.subTest(workflow=wf, stage=stage):
                generated = _ENGINE_HEADINGS.split(prompt, maxsplit=1)
                tail = prompt[len(generated[0]):] if len(generated) > 1 else ""
                self.assertEqual(path_token.findall(tail), [])


class TestConsolidateSchemaInputs(unittest.TestCase):
    """Each isolated consolidate-schema stage reads its upstream files by own-cwd path."""

    def _task(self, stage: str) -> str:
        for wf, st, _, prompt in _ROWS:
            if (wf, st) == ("workflows/resume/consolidate-schema.yaml", stage):
                return re.sub(r"\s+", " ", _task(prompt))
        raise AssertionError(f"stage {stage} not rendered")

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
        self.assertNotIn(f"only under {_WS_MARK}", task)

    def test_e2e_tmp_cleanup_is_a_trap_not_a_manual_step(self) -> None:
        """A prose "delete it before you finish" instruction can be skipped by
        an interrupted run or a failing command. The trap must be registered
        in the SAME shell, immediately after $E2E_TMP is created, so cleanup
        does not depend on the agent remembering a later rm -rf."""
        task = self._task("test-e2e-data")
        self.assertIn("trap 'rm -rf \"$E2E_TMP\"' EXIT", task)
        create_idx = task.index("E2E_TMP=$(mktemp")
        trap_idx = task.index("trap 'rm -rf \"$E2E_TMP\"' EXIT")
        self.assertLess(
            create_idx, trap_idx,
            msg="trap must be registered immediately after E2E_TMP is created, "
            "not after other commands run in between",
        )
        # No longer a bare prose "delete it ... before you finish" instruction:
        # the only rm -rf left is the trap body itself.
        self.assertEqual(task.count("rm -rf"), 1)

    def test_e2e_tmp_is_verified_outside_every_checkout(self) -> None:
        """mktemp -d alone honors TMPDIR, which can point inside a checkout —
        not just the agent's own worktree or the main checkout, but any other
        linked worktree too. The stage must use an explicit outside-checkout
        template AND enumerate every root from `git worktree list --porcelain`
        (which includes the main checkout) rather than checking only two
        fixed roots."""
        task = self._task("test-e2e-data")
        self.assertIn('mktemp -d "${TMPDIR:-/tmp}/e2e-schema.XXXXXX"', task)
        self.assertIn("git worktree list --porcelain", task)
        # Enumeration failure (a git error) must abort rather than proceed
        # with an empty root set. The git call must NOT be piped straight
        # into awk with the exit check on the pipeline -- awk exits 0 on
        # empty input regardless of git's own status, so that form silently
        # swallows a git failure. git's exit status must be checked on its
        # own line.
        self.assertIn(
            "WT_LIST=$(git worktree list --porcelain) || exit 1", task
        )
        self.assertNotIn("git worktree list --porcelain | awk", task)
        # A repo always has at least one worktree, so zero enumerated roots
        # means enumeration broke, not that no checkouts exist -- abort.
        self.assertIn('[ -s "$ROOTS_FILE" ]', task)
        # The roots must be read from a real file via `while read ... done <
        # file`, not a bare `for ROOT in $ROOTS` word-split (a no-op in zsh,
        # which does not split unquoted expansions on IFS by default) or a
        # piped `while read` (runs in a subshell, so its `exit 1` would not
        # stop the parent shell). Check the code form directly rather than
        # forbidding the anti-pattern's name, which the explanatory prose
        # legitimately mentions.
        self.assertIn("while IFS= read -r ROOT; do", task)
        self.assertIn('done < "$ROOTS_FILE"', task)
        # The verification must abort the sample run rather than proceed.
        verify_idx = task.index("git worktree list --porcelain")
        abort_idx = task.index("aborting")
        self.assertLess(verify_idx, abort_idx)

    def test_e2e_tmp_check_enumerates_not_two_fixed_roots(self) -> None:
        """The old form hardcoded exactly two roots (own worktree, main
        checkout) via `git rev-parse --show-toplevel` / `--git-common-dir`.
        That misses a TMPDIR pointing inside a THIRD, unrelated linked
        worktree. The check must enumerate every worktree root instead of
        naming two fixed ones."""
        task = self._task("test-e2e-data")
        self.assertNotIn("git rev-parse --show-toplevel", task)
        self.assertNotIn("git rev-parse --path-format=absolute --git-common-dir", task)
        self.assertIn("pwd -P", task)
