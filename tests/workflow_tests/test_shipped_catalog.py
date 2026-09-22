"""Contract tests for the SHIPPED workflow catalog under ``workflows/``.

Every other test in this package builds synthetic YAML in a tmp_path fixture,
which exercises the engine but never the 57 workflow definitions the repo
actually ships. A definition could therefore be committed with a broken DAG,
a dangling ``depends_on``, or a stage whose contract is silently discarded at
dispatch, and nothing in ``make test`` or CI would notice — ``./bin/workflow
lint`` is a thing an author has to remember to run by hand.

These tests close that gap. They read the real files and assert properties
that must hold for every shipped workflow, so a broken definition fails the
suite rather than failing at run time in front of a user.

Scope note: this is a *static* contract check, not an execution test. It
proves each definition parses, compiles and declares its stages coherently —
not that the agents it spawns do the right thing.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from pathlib import Path

import yaml

from workflow.linter import lint_workflow
from workflow.parser import parse_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / "workflows"
BASELINE_PATH = Path(__file__).resolve().parent / "shipped_catalog_baseline.json"

# Stage kinds whose prompt builder does NOT include stage.description.
# See workflow/dispatch.py's _validate(): it builds its prompt from the
# validation block's strategy/criteria/domain_rules plus a generic findings
# instruction, and never reads stage.spec.description. A validate stage that
# keeps its contract in description therefore ships a contract no agent sees.
_DESCRIPTION_DROPPING_KINDS = frozenset({"validate"})

# A description longer than this, on a description-dropping kind, is treated
# as a real contract rather than a one-line directive. The threshold is
# deliberately generous: the point is to catch stages carrying a multi-step
# protocol, not to police wording.
_CONTRACT_DESCRIPTION_CHARS = 600


def _catalog_files() -> list[Path]:
    """Return every workflow YAML shipped in the repo, sorted for stable output."""
    return sorted(WORKFLOWS_DIR.rglob("*.yaml"))


def _baseline() -> dict[str, set[str]]:
    """Load the grandfathered-violations baseline as sets of ``file::stage`` keys.

    The gate below was added long after the catalog it checks, so a strict
    pass would have demanded a 79-violation cleanup across 18 workflows
    before anything could land. Instead these are recorded once and the test
    blocks only NEW violations — the same ratchet the repo already uses for
    mypy (typecheck-baseline.json and its legacy_files).
    """
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {
        key: set(value)
        for key, value in raw.items()
        if not key.startswith("_") and isinstance(value, list)
    }


def _stage_key(path: Path, stage_name: object) -> str:
    """Build the ``<repo-relative file>::<stage>`` key used by the baseline."""
    return f"{path.relative_to(REPO_ROOT)}::{stage_name}"


def _iter_stages() -> Iterator[tuple[Path, dict]]:
    """Yield every ``(workflow path, stage dict)`` pair in the catalog."""
    for path in _catalog_files():
        for stage in _load_raw(path).get("stages") or []:
            if isinstance(stage, dict):
                yield path, stage


def _iter_isolated_stages() -> Iterator[tuple[Path, dict]]:
    """Yield only the stages that declare ``isolation: worktree``."""
    for path, stage in _iter_stages():
        agent = stage.get("agent") or {}
        if isinstance(agent, dict) and agent.get("isolation") == "worktree":
            yield path, stage


def _iter_validate_stages() -> Iterator[tuple[Path, dict]]:
    """Yield only the stages whose kind drops ``description`` at dispatch."""
    for path, stage in _iter_stages():
        if stage.get("kind") in _DESCRIPTION_DROPPING_KINDS:
            yield path, stage


def _self_contained_workflows() -> Iterator[tuple[Path, list[dict], set[object]]]:
    """Yield ``(path, stages, stage names)`` for workflows with no ``include:``.

    Files with an ``include:`` block are skipped: a fragment injects prefixed
    stages that a local reference may legitimately name, and those stages are
    not visible in the raw YAML.
    """
    for path in _catalog_files():
        raw = _load_raw(path)
        stages = [s for s in (raw.get("stages") or []) if isinstance(s, dict)]
        if not stages or raw.get("include"):
            continue
        yield path, stages, {s.get("name") for s in stages}


def _missing_stage_references(field: str) -> list[str]:
    """Return ``stage -> field -> target`` references naming no real stage.

    Shared by the depends_on and reads_from checks, which differ only in the
    field they read.
    """
    return [
        f"{_stage_key(path, stage.get('name'))} {field} -> '{target}' (no such stage)"
        for path, stages, names in _self_contained_workflows()
        for stage in stages
        for target in stage.get(field) or []
        if target not in names
    ]


def _load_raw(path: Path) -> dict:
    """Parse a workflow YAML to a plain dict without running the workflow parser."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _is_fragment(raw: dict) -> bool:
    """Return True for include-only fragments, which cannot stand alone."""
    return bool(raw.get("fragment"))


class TestShippedCatalogLints(unittest.TestCase):
    """Every shipped workflow must lint clean."""

    def test_catalog_is_non_empty(self) -> None:
        """Guard against the whole suite silently passing on an empty glob.

        Without this, a wrong WORKFLOWS_DIR would make every subtest below
        iterate zero files and report success — the same false-clean shape as
        a scanner that reports 0 issues because it scanned 0 files.
        """
        files = _catalog_files()
        self.assertGreater(
            len(files), 20, f"expected a populated catalog, found {len(files)} files"
        )

    def test_every_workflow_lints_without_errors(self) -> None:
        """No shipped workflow may have lint errors.

        Warnings are allowed (several are advisory, e.g. an unrecognised
        validates_output check name kept for forward compatibility); errors
        are not.
        """
        for path in _catalog_files():
            with self.subTest(workflow=str(path.relative_to(REPO_ROOT))):
                result = lint_workflow(path)
                messages = [
                    f"{e.stage or '<file>'}.{e.field or '<none>'}: {e.message}"
                    for e in result.errors
                ]
                self.assertTrue(
                    result.valid,
                    f"lint errors in {path.relative_to(REPO_ROOT)}:\n  "
                    + "\n  ".join(messages),
                )


class TestShippedCatalogParses(unittest.TestCase):
    """Every non-fragment workflow must parse into a coherent DAG."""

    def test_non_fragments_parse(self) -> None:
        """A runnable workflow must parse without raising."""
        for path in _catalog_files():
            raw = _load_raw(path)
            if _is_fragment(raw):
                continue
            with self.subTest(workflow=str(path.relative_to(REPO_ROOT))):
                # parse_workflow raises WorkflowParseError on a bad definition;
                # letting it propagate here is the assertion.
                defn = parse_workflow(path)
                self.assertTrue(
                    defn.stages,
                    f"{path.relative_to(REPO_ROOT)} parsed to zero stages",
                )

    def test_depends_on_references_a_real_stage(self) -> None:
        """A dangling depends_on silently drops a stage from the DAG."""
        dangling = _missing_stage_references("depends_on")
        self.assertEqual(
            dangling,
            [],
            "stages depend on names that are not stages in their workflow:\n  "
            + "\n  ".join(dangling),
        )

    def test_reads_from_references_a_real_stage(self) -> None:
        """reads_from naming a nonexistent stage yields an empty input."""
        dangling = _missing_stage_references("reads_from")
        self.assertEqual(
            dangling,
            [],
            "stages read from names that are not stages in their workflow:\n  "
            + "\n  ".join(dangling),
        )


class TestValidateKindContractNotDropped(unittest.TestCase):
    """A kind:validate stage must not hide its contract in description.

    workflow/dispatch.py's _validate() builds the agent prompt from the
    validation block alone. A validate stage carrying a long, prescriptive
    description ships a contract that never reaches the agent, and no lint
    or compile step reports it — the stage runs and produces plausible
    findings, so the failure looks like a working stage.
    """

    def test_validate_stages_declare_a_validation_block(self) -> None:
        """Every kind:validate stage needs validation.criteria to say anything."""
        grandfathered = _baseline()["validate_stage_missing_validation_block"]
        offenders: list[str] = []
        for path, stage in _iter_validate_stages():
            key = _stage_key(path, stage.get("name"))
            validation = stage.get("validation")
            has_criteria = isinstance(validation, dict) and validation.get("criteria")
            if not has_criteria and key not in grandfathered:
                offenders.append(key)
        self.assertEqual(
            offenders,
            [],
            "kind:validate stages declare no validation.criteria. Their "
            "description is dropped at dispatch (workflow/dispatch.py's "
            "_validate), so these stages would carry no contract at all. "
            "Add validation.criteria, or use kind:execute:\n  "
            + "\n  ".join(offenders),
        )

    def test_long_contracts_do_not_live_on_validate_stages(self) -> None:
        """A multi-step protocol in description must use kind:execute.

        This is the check that caught qwen-local-handler's
        adversarial-test-review and integrate stages, whose descriptions
        carried an eight-item review protocol and a full gate sequence that
        dispatch would have discarded.
        """
        grandfathered = _baseline()["validate_stage_long_description"]
        offenders: list[str] = []
        for path, stage in _iter_validate_stages():
            key = _stage_key(path, stage.get("name"))
            size = len(str(stage.get("description") or ""))
            if size > _CONTRACT_DESCRIPTION_CHARS and key not in grandfathered:
                offenders.append(f"{key} ({size} chars)")
        self.assertEqual(
            offenders,
            [],
            "kind:validate stages carry a description longer than "
            f"{_CONTRACT_DESCRIPTION_CHARS} chars, which dispatch discards. "
            "Switch these to kind:execute and keep the contract in "
            "description, or move the contract into validation.criteria:\n  "
            + "\n  ".join(offenders),
        )


class TestIsolatedStagesCommit(unittest.TestCase):
    """An isolation:worktree stage that writes code must commit it.

    .claude/skills/workflow/SKILL.md's isolation protocol is explicit: git
    merge moves commits, not uncommitted files. An isolated agent that edits
    its worktree and returns without committing leaves nothing to merge —
    the merge succeeds against an empty branch and the stage reports success
    while no code lands.
    """

    def test_isolated_stages_mention_committing(self) -> None:
        """Every isolated stage's description must tell the agent to commit."""
        grandfathered = _baseline()["isolated_stage_without_commit"]
        offenders = [
            _stage_key(path, stage.get("name"))
            for path, stage in _iter_isolated_stages()
            if "commit" not in str(stage.get("description") or "").lower()
            and _stage_key(path, stage.get("name")) not in grandfathered
        ]
        self.assertEqual(
            offenders,
            [],
            "stages declare isolation:worktree but never instruct the agent "
            "to commit, so their edits cannot be merged back and will be "
            "silently lost (see .claude/skills/workflow/SKILL.md, isolation "
            "protocol step c):\n  " + "\n  ".join(offenders),
        )


class TestBaselineDoesNotRot(unittest.TestCase):
    """The grandfathered list must shrink as workflows are repaired.

    Without this, a baseline becomes a place violations go to be forgotten:
    a stage could be fixed and its entry would linger, quietly re-permitting
    the same defect if it were ever reintroduced. Failing on a stale entry
    forces the file to track reality.
    """

    def test_every_baselined_entry_still_names_a_real_stage(self) -> None:
        """A baseline entry pointing at a deleted file or stage is stale."""
        known = {
            _stage_key(path, stage.get("name")) for path, stage in _iter_stages()
        }
        stale: list[str] = []
        for category, entries in _baseline().items():
            stale.extend(
                f"{category}: {entry}" for entry in sorted(entries - known)
            )
        self.assertEqual(
            stale,
            [],
            "baseline entries name stages that no longer exist — remove "
            "these lines from shipped_catalog_baseline.json:\n  "
            + "\n  ".join(stale),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
