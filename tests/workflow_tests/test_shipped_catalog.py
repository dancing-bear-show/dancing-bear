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
import re
import unittest
from collections.abc import Iterator
from pathlib import Path

import yaml

from workflow.compiler import compile_workflow, validate_dag_contracts
from workflow.linter import lint_workflow
from workflow.models import WorkflowDefinition
from workflow.parser import parse_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / "workflows"
BASELINE_PATH = Path(__file__).resolve().parent / "shipped_catalog_baseline.json"

# The ONLY keys in the baseline that are not violation categories. Kept as an
# explicit allowlist rather than an `_`-prefix rule: a prefix rule lets any
# category be exempted from every gate by renaming it, which is the ratchet
# bypass this file exists to prevent.
_BASELINE_METADATA_KEYS = frozenset({"_comment", "_generated_from"})

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

# Affirmative commit instructions used by shipped isolated stages: an
# imperative "commit ... (before) finish/done" (matching "COMMIT BEFORE
# FINISHING", "Commit your edits before you finish", etc.) or a literal
# `git commit` invocation. Merely containing the substring "commit" is not
# enough — a stage can mention committing only to forbid it (see
# _NEGATIVE_COMMIT_RE below), which must not satisfy this check.
#
# Matching this pattern is necessary but NOT sufficient: the pattern starts
# at the "commit" token and so cannot see a negator in front of it, which
# means "Do not commit before you finish" matches it just as readily as
# "COMMIT BEFORE FINISHING". Every use must go through
# _has_unnegated_commit_instruction() below, which re-checks the lead-in.
_AFFIRMATIVE_COMMIT_RE = re.compile(
    r"commit\b[^.]{0,80}\bfinish|\bgit\s+commit\b", re.IGNORECASE | re.DOTALL
)

# A negator immediately in front of a commit instruction, which inverts it.
# Anchored with \Z so it matches only at the very END of the text preceding a
# candidate match — i.e. the words that actually govern THAT occurrence.
#
# Scoping this to the lead-in rather than scanning the whole description is
# the point. A correct description routinely contains a nearby prohibition
# that governs something else: "commit your work before you finish; never
# `git add -A`" forbids a staging shortcut, not the commit, and
# qwen-local-handler.yaml's impl-heartbeat tells the agent to commit and then
# to "skip the commit entirely" on its no-change route. A whole-description
# negative scan would reject both of those real, shipped stages.
#
# The negator list covers prohibitions phrased as avoidance or omission as well
# as plain negation: "avoid git commit", "skip the commit", "refrain from
# committing", "commit nothing; stash rather than commit". Each is a lead-in
# that, left out, would let an explicit opt-out satisfy the gate by containing
# the literal `git commit` or "commit ... finish".
#
# Erring broad is the safe direction. A missed negator is SILENT — the gate
# reads as satisfied while the edits are lost at merge. A spurious one is LOUD
# — the gate fails naming the stage, and the author rewords. Double negatives
# ("do not finish without a `git commit`") land on the loud side for that
# reason, and are best rewritten as the plain imperative anyway.
_NEGATORS = (
    r"never|nor"
    r"|do\s+not|does\s+not|don['’]t|doesn['’]t"
    r"|must\s+not|mustn['’]t|should\s+not|shouldn['’]t"
    r"|will\s+not|won['’]t|may\s+not|need\s+not|needn['’]t"
    r"|cannot|can\s+not|can['’]t|without"
    r"|avoid(?:ing)?|skip(?:ping)?|refrain(?:ing)?\s+from"
    r"|omit(?:ting)?|forgo(?:ing)?|instead\s+of|rather\s+than"
    r"|no\s+need\s+to|not\s+(?:allowed|permitted)\s+to"
    r"|(?:forbidden|prohibited)\s+(?:to|from)"
)

# Words that start a new clause, and so end the reach of a negator before
# them: "never `git add -A` — and commit them before you finish" forbids the
# staging shortcut, not the commit. Em and en dashes are excluded from the
# filler for the same reason.
_CLAUSE_BREAK = r"\b(?:and|then|but|or|so)\b"

# The optional filler permits a short object between the negator and the verb
# ("do not EVER commit", "must not, under any circumstances, commit", "skip
# the commit") without reaching back across a sentence or clause boundary to
# borrow an unrelated negator.
#
# Bare "no" and "not" get NO filler: they negate only when directly adjacent
# ("no `git commit`", "not commit"). Given filler they would swallow ordinary
# conditions such as "if there are no failures, commit before you finish".
_NEGATED_LEADIN_RE = re.compile(
    rf"\b(?:{_NEGATORS})\b(?:(?!{_CLAUSE_BREAK})[^.;:\n–—]){{0,30}}\Z"
    r"|\bno(?:t)?\s+[`'\"]?\Z",
    re.IGNORECASE,
)


def _has_unnegated_commit_instruction(description: str) -> bool:
    """Return True if the text gives at least one commit instruction that stands.

    ``_AFFIRMATIVE_COMMIT_RE`` begins at the "commit" token, so on its own it
    cannot tell "COMMIT BEFORE FINISHING" from "Do not commit before you
    finish" — both contain the same span. This re-reads the text immediately
    preceding each match and discards the ones a negator inverts.

    It requires only ONE surviving instruction rather than demanding all be
    clean, because a description that says "commit before you finish" and
    later carves out "on route (a), skip the commit entirely" is correct: it
    instructs the agent to commit in the case where there is anything to
    commit. Demanding every occurrence be un-negated would reject that.
    """
    for match in _AFFIRMATIVE_COMMIT_RE.finditer(description):
        if not _NEGATED_LEADIN_RE.search(description[: match.start()]):
            return True
    return False

# Roles whose whole purpose is producing edits. For these the commit opt-out
# below is NOT available: their work reaches the branch only as commits, so
# "do not commit" in an isolated stage means the edits are silently discarded
# at merge, which is the defect the gate exists to catch rather than an
# exemption from it.
_CODE_WRITING_ROLES = frozenset({"code-writer", "code-writer-opus", "tester", "tester-opus", "ci-fixer"})

# An explicit opt-out: the stage is isolated but must not commit (e.g. a
# read-only review stage that would corrupt a shared tree if it did). This is
# a legitimate pattern, not the violation the gate exists to catch.
_NEGATIVE_COMMIT_RE = re.compile(
    r"(never|do not|don't|must not)\s+commit", re.IGNORECASE
)


# Sample values for trigger params that are ``required`` but ship with a blank
# default, keyed by (workflow path relative to the repo root, param name).
# compile_workflow rejects a blank required param, so the compile gate below
# must supply one; a required param with a non-blank default needs no entry,
# since its default already has to satisfy its own rule at parse time. Each
# sample is checked against the param's real rules by compiling with it.
# test_required_blank_params_have_samples fails on a missing entry AND on a
# stale one, so this table cannot silently fall out of step with the catalog.
_REQUIRED_PARAM_SAMPLES: dict[tuple[str, str], str] = {
    ("workflows/code/review-fix-threads.yaml", "pr_number"): "391",
}


def _catalog_files() -> list[Path]:
    """Return every workflow YAML shipped in the repo, sorted for stable output."""
    return sorted(WORKFLOWS_DIR.rglob("*.yaml"))


def _required_blank_params(defn: WorkflowDefinition) -> set[str]:
    """Required trigger params whose declared default is blank (needs a sample)."""
    params = defn.trigger.params or {}
    return {name for name in defn.trigger.rules.required if not params.get(name, "").strip()}


def _sample_params(path: Path, defn: WorkflowDefinition) -> dict[str, str]:
    """The sample overrides the compile gate passes for *path*'s blank required params."""
    rel = str(path.relative_to(REPO_ROOT))
    return {
        name: _REQUIRED_PARAM_SAMPLES[(rel, name)]
        for name in _required_blank_params(defn)
        if (rel, name) in _REQUIRED_PARAM_SAMPLES
    }


def _baseline() -> dict[str, set[str]]:
    """Load the grandfathered-violations baseline as sets of ``file::stage`` keys.

    The gate below was added long after the catalog it checks, so a strict
    pass would have demanded cleaning up every pre-existing violation before
    anything could land. Instead these are recorded once and the test blocks
    only NEW violations — the same ratchet the repo already uses for mypy
    (typecheck-baseline.json and its legacy_files).

    No count is quoted here on purpose: an earlier revision said 79, which
    went stale the moment a fourth category was added. The authoritative
    per-category numbers are the ceilings in
    ``TestBaselineDoesNotRot.test_baseline_never_grows``, and the file itself.
    """
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    # Metadata keys are an explicit allowlist, not "anything starting with _".
    # Treating every underscore key as metadata means a category renamed
    # `_ignored` disappears from the live gates AND from both rot checks, so
    # its entries are grandfathered permanently — the ratchet bypassed by a
    # rename. An unexpected underscore key is therefore an error, not a hint.
    unknown_meta = sorted(
        k for k in raw if k.startswith("_") and k not in _BASELINE_METADATA_KEYS
    )
    if unknown_meta:
        raise AssertionError(
            f"unrecognised underscore-prefixed baseline keys: {unknown_meta}. "
            "Only "
            f"{sorted(_BASELINE_METADATA_KEYS)} are metadata; any other "
            "underscore key would silently exempt its entries from every "
            "gate. Add it to _BASELINE_METADATA_KEYS if it really is "
            "metadata, or rename it to a real category."
        )

    categories = {k: v for k, v in raw.items() if k not in _BASELINE_METADATA_KEYS}

    # Fail on a malformed category rather than skipping it. An
    # ``isinstance(value, list)`` filter here would silently drop any category
    # whose value is not a list, and a dropped category is consulted by no
    # gate and by no rot check — so a malformed or newly added one bypasses
    # the whole ratchet while every test stays green. Underscore-prefixed keys
    # are metadata and are excluded above by design.
    malformed = sorted(k for k, v in categories.items() if not isinstance(v, list))
    if malformed:
        raise AssertionError(
            f"baseline categories are not lists: {malformed}. A non-list "
            "category is silently ignored by every gate, which makes the "
            "ratchet bypassable. Fix the shape in "
            f"{BASELINE_PATH.name} (metadata keys must start with '_')."
        )
    return {key: set(value) for key, value in categories.items()}


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


def _instructs_commit(description: str) -> bool:
    """Return True if an isolated stage's description satisfies the commit gate.

    A stage passes either by giving an affirmative commit instruction (an
    imperative "commit ... finish" or a literal `git commit`) or by
    explicitly declaring it must never commit — a legitimate opt-out for a
    read-only isolated stage. The substring "commit" alone proves neither:
    a stage can say "Never commit from this stage" and contain it while
    giving no instruction to commit at all.
    """
    return bool(
        _has_unnegated_commit_instruction(description)
        or _NEGATIVE_COMMIT_RE.search(description)
    )


def _iter_contract_warning_pairs() -> Iterator[tuple[Path, dict]]:
    """Yield one synthetic ``(path, stage-like dict)`` per reads_from pair.

    Shaped to match the other iterators so ``TestBaselineDoesNotRot`` can key
    it with ``_stage_key`` unchanged: ``name`` is ``stage->upstream``, which
    is the granularity a contract warning actually has (a stage can read from
    several upstreams and be wrong about only one). ``declares_outputs`` is
    what the predicate below reads.
    """
    for path in _catalog_files():
        if _is_fragment(_load_raw(path)):
            continue
        # Must go through parse_workflow, not the raw YAML: a workflow with an
        # `include:` gets its stages from a fragment, so a raw read sees none
        # of them and the pair keys silently come back empty. The live gate
        # uses the parser, so this must too or the two cannot agree.
        defn = parse_workflow(path)
        by_name = {s.name: s for s in defn.stages}
        for stage in defn.stages:
            for upstream_name in stage.reads_from:
                upstream = by_name.get(upstream_name)
                if upstream is None:
                    # A dangling reads_from is a different gate's finding.
                    continue
                yield path, {
                    "name": f"{stage.name}->{upstream_name}",
                    "declares_outputs": bool(upstream.writes_to),
                }


def _upstream_declares_outputs(pair: dict) -> bool:
    """Return True when the upstream of this reads_from pair has writes_to.

    The positive form of ``test_no_new_reads_from_contract_warnings``: a pair
    is compliant once its upstream declares outputs, so a baseline entry for
    a repaired pair is reported as stale.
    """
    return bool(pair.get("declares_outputs"))


def _has_validation_block(stage: dict) -> bool:
    """Return True if a kind:validate stage declares validation.criteria.

    The positive form of the check in
    ``test_validate_stages_declare_a_validation_block`` — used both there and
    by the baseline-rot check below so the two can never disagree about what
    counts as compliant.
    """
    validation = stage.get("validation")
    return bool(isinstance(validation, dict) and validation.get("criteria"))


def _has_short_description(stage: dict) -> bool:
    """Return True if a kind:validate stage's description is within budget.

    The positive form of the check in
    ``test_long_contracts_do_not_live_on_validate_stages``.
    """
    return len(str(stage.get("description") or "")) <= _CONTRACT_DESCRIPTION_CHARS


def _commits(stage: dict) -> bool:
    """Return True if an isolated stage's description satisfies the commit gate.

    The positive form of the check in
    ``test_isolated_stages_mention_committing``.

    The negative opt-out ("never commit from this stage") is honoured only
    for roles that do not write code. A `code-writer` or `tester` in a
    worktree produces edits that reach the branch ONLY as commits, so
    declaring that it must not commit does not make the stage safe — it
    guarantees the work is lost at merge while the gate reads as satisfied.
    Those roles must give an affirmative commit instruction; only a
    read-only role (a `critic` reviewing a tree, say) may opt out.
    """
    description = str(stage.get("description") or "")
    agent = stage.get("agent") or {}
    role = agent.get("role") if isinstance(agent, dict) else None
    if role in _CODE_WRITING_ROLES:
        return _has_unnegated_commit_instruction(description)
    return _instructs_commit(description)


# Maps each baseline category to the predicate that decides whether a stage
# is currently COMPLIANT with the rule it was grandfathered against. Shared
# by the live gates above and TestBaselineDoesNotRot below: if these ever
# drift from what a gate actually checks, the baseline-rot test and the gate
# it mirrors can silently disagree.
_CATEGORY_COMPLIANCE: dict[str, tuple] = {
    "validate_stage_missing_validation_block": (_iter_validate_stages, _has_validation_block),
    "validate_stage_long_description": (_iter_validate_stages, _has_short_description),
    "isolated_stage_without_commit": (_iter_isolated_stages, _commits),
    "reads_from_upstream_without_writes_to": (
        _iter_contract_warning_pairs,
        _upstream_declares_outputs,
    ),
}


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

    def test_non_fragments_parse_and_compile(self) -> None:
        """A runnable workflow must parse AND compile without raising.

        Parsing alone is too weak a gate to claim the catalog is sound: a
        definition can parse cleanly and still fail at ``compile_workflow``,
        which is the first thing a real run does. Compiling here costs a few
        milliseconds per file and is pure — it resolves refs and computes
        parallel groups, it does not execute anything — so the gate covers
        the whole static path a user hits before any agent is spawned.

        Verified by injecting a defect rather than assumed: replacing a real
        ``when:`` expression with an unparseable one fails this test with
        ``WorkflowCompileError`` while the parse-only gate stayed green.
        Note the failure has to come through ``spec.outputs`` or ``when`` —
        an unknown top-level key such as a bare ``template:`` is dropped by
        the parser and reaches no compile check at all, so it is not a
        defect this gate can see.
        """
        for path in _catalog_files():
            raw = _load_raw(path)
            if _is_fragment(raw):
                continue
            with self.subTest(workflow=str(path.relative_to(REPO_ROOT))):
                # parse_workflow raises WorkflowParseError and compile_workflow
                # raises WorkflowCompileError on a bad definition; letting
                # either propagate here is the assertion.
                defn = parse_workflow(path)
                self.assertTrue(
                    defn.stages,
                    f"{path.relative_to(REPO_ROOT)} parsed to zero stages",
                )
                manifest = compile_workflow(
                    defn,
                    project_root=REPO_ROOT,
                    trigger_params=_sample_params(path, defn),
                )
                self.assertEqual(
                    set(manifest.resolved_stages),
                    {s.name for s in defn.stages},
                    f"{path.relative_to(REPO_ROOT)}: compile dropped or "
                    "invented stages relative to the parsed definition",
                )
                # Every stage must land in a parallel group. A stage missing
                # from the schedule never runs, and the run still reports
                # success — the quietest possible failure.
                scheduled = {n for group in manifest.parallel_groups for n in group}
                self.assertEqual(
                    scheduled,
                    set(manifest.resolved_stages),
                    f"{path.relative_to(REPO_ROOT)}: stages resolved but "
                    "never scheduled into a parallel group",
                )

    def test_required_blank_params_have_samples(self) -> None:
        """Every required-but-blank-default param has a sample, and no sample is stale.

        Without a sample the compile gate above fails with "required but
        blank" — correct, but it reads as a broken workflow rather than a
        missing table entry. A stale entry (its param is no longer required,
        or now has a default) is reported too, so the table shrinks with the
        catalog instead of accumulating dead rows.
        """
        needed: set[tuple[str, str]] = set()
        for path in _catalog_files():
            if _is_fragment(_load_raw(path)):
                continue
            rel = str(path.relative_to(REPO_ROOT))
            needed |= {(rel, name) for name in _required_blank_params(parse_workflow(path))}
        self.assertEqual(
            sorted(needed - set(_REQUIRED_PARAM_SAMPLES)),
            [],
            "required trigger params with a blank default and no sample in "
            "_REQUIRED_PARAM_SAMPLES; add one that satisfies the param's rule",
        )
        self.assertEqual(
            sorted(set(_REQUIRED_PARAM_SAMPLES) - needed),
            [],
            "stale _REQUIRED_PARAM_SAMPLES entries: not a required param with a blank default",
        )

    def test_no_new_reads_from_contract_warnings(self) -> None:
        """A stage reading an upstream that declares no outputs gets nothing.

        ``compile_workflow`` does NOT run this check — ``validate_dag_contracts``
        is a separate function the CLI calls on its own, so the compile gate
        above passes a workflow whose ``reads_from`` names an upstream with no
        ``writes_to``. That stage's agent then receives an empty input and
        produces confident output from nothing, which is the quiet failure
        this catalog test exists to prevent.

        Ratcheted rather than strict: 9 such warnings ship today across 3
        files, so the gate blocks NEW ones and leaves those to be repaired on
        their own schedule. Key is ``file::stage->upstream``.
        """
        baselined = _baseline().get("reads_from_upstream_without_writes_to", set())
        new: list[str] = []
        for path in _catalog_files():
            raw = _load_raw(path)
            if _is_fragment(raw):
                continue
            defn = parse_workflow(path)
            rel = path.relative_to(REPO_ROOT)
            for warning in validate_dag_contracts(defn):
                key = f"{rel}::{warning.stage}->{warning.upstream}"
                if key not in baselined:
                    new.append(f"{key}: {warning.message}")
        self.assertEqual(
            new,
            [],
            "new reads_from contract warnings — the upstream stage declares "
            "no writes_to, so the downstream agent reads an empty input:\n  "
            + "\n  ".join(new),
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
            if not _has_validation_block(stage) and key not in grandfathered:
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
            if not _has_short_description(stage) and key not in grandfathered:
                size = len(str(stage.get("description") or ""))
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
            if not _commits(stage)
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


class TestCommitInstructionPredicate(unittest.TestCase):
    """``_has_unnegated_commit_instruction`` must read the lead-in, not the token.

    Every negated case is paired with its affirmative twin so a test cannot
    pass merely because the predicate rejects everything (or accepts it).
    """

    def _assert_verdicts(self, cases: dict[str, bool]) -> None:
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIs(_has_unnegated_commit_instruction(text), expected)

    def test_original_negators_invert_the_instruction(self) -> None:
        self._assert_verdicts({
            "Do not commit before you finish.": False,
            "Never run git commit here.": False,
            "You must not, under any circumstances, commit before you finish.": False,
            "Commit before you finish.": True,
        })

    def test_avoidance_and_omission_negators_invert_the_instruction(self) -> None:
        self._assert_verdicts({
            "Avoid git commit in this stage.": False,
            "Avoid `git commit` in this stage.": False,
            "Avoiding git commit keeps the tree clean.": False,
            "Skip git commit.": False,
            "Skipping the git commit is fine.": False,
            "Refrain from git commit.": False,
            "Omit the git commit.": False,
            "Forgo the git commit.": False,
            "Stash rather than git commit.": False,
            "Use stash instead of git commit.": False,
            "There is no need to git commit.": False,
            "You are not allowed to git commit.": False,
            "You are forbidden to git commit.": False,
            "Neither stash nor git commit.": False,
            "Run git commit in this stage.": True,
        })

    def test_modal_negators_invert_the_instruction(self) -> None:
        self._assert_verdicts({
            "You shouldn't commit before you finish.": False,
            "You should not commit before you finish.": False,
            "You mustn't commit before you finish.": False,
            "You mustn’t commit before you finish.": False,
            "The agent won't git commit.": False,
            "You need not commit before you finish.": False,
            "You should commit before you finish.": True,
        })

    def test_bare_no_and_not_negate_only_when_adjacent(self) -> None:
        self._assert_verdicts({
            "Make no git commit.": False,
            "Make no `git commit`.": False,
            "Do NOT git commit.": False,
            # Given any filler, "no" would swallow an ordinary condition.
            "If there are no failures, commit before you finish.": True,
            "The note field is optional; commit before you finish.": True,
        })

    def test_negator_does_not_reach_across_a_clause_break(self) -> None:
        # consolidate-schema.yaml::test-e2e-data: the "never" governs the
        # staging shortcut, and the dash plus "and" start a new clause.
        self._assert_verdicts({
            "Stage them by name — never `git add -A` — and commit them "
            "before you finish.": True,
            "Never `git add -A`, then git commit.": True,
            "Skip the lint step and commit before you finish.": True,
            "Never stage with -A. Commit before you finish.": True,
            "Do not stage with -A; commit before you finish.": True,
        })

    def test_one_standing_instruction_survives_a_negated_carve_out(self) -> None:
        # qwen-local-handler.yaml::impl-heartbeat: commit, but skip it on the
        # no-change route. The carve-out is itself negated and must not poison
        # the affirmative instruction.
        heartbeat = (
            "COMMIT BEFORE FINISHING, IF YOU CHANGED ANY FILE.\n"
            "  git add src/worker/queue_ops.py\n"
            '  git commit -m "fix(worker): keep a live heartbeat"\n'
            "Route (a) is NO code change by design, so there is nothing to "
            "stage and `git commit` would fail with an empty index. On route "
            "(a), skip the commit entirely, record commit_sha: null and finish."
        )
        carve_out_only = (
            "On route (a), skip the commit entirely, record commit_sha: null "
            "and finish."
        )
        self._assert_verdicts({heartbeat: True, carve_out_only: False})

    def test_commit_sha_and_plural_commits_are_not_instructions(self) -> None:
        self._assert_verdicts({
            'Record "commit_sha": "<sha>" before you finish.': False,
            "git merge moves COMMITS, not files, so finish cleanly.": False,
        })


class TestBaselineDoesNotRot(unittest.TestCase):
    """The grandfathered list must shrink as workflows are repaired.

    Without this, a baseline becomes a place violations go to be forgotten:
    a stage could be fixed and its entry would linger, quietly re-permitting
    the same defect if it were ever reintroduced. Failing on a stale entry
    forces the file to track reality.
    """

    def test_baseline_never_grows(self) -> None:
        """A ratchet that can be widened is not a ratchet.

        The gates above compare against whatever this file currently says, so
        a new violation could be waved through by appending its key here —
        the test stays green and the ratchet has been loosened rather than
        tightened, silently and in the same commit that introduced the
        defect.

        A merge-base comparison would be the stronger check, but is not
        available: this file does not exist on main yet, so `git show
        main:<path>` fails and the gate would be vacuous on the very branch
        that introduces it. A hard ceiling is enforceable today and needs no
        git access, which also keeps it working in a shallow CI checkout.

        Lower these numbers when you repair a violation; the rot tests above
        already force removal of entries that no longer apply. Raising one is
        a deliberate act that shows up in review as exactly what it is.
        """
        ceilings = {
            "validate_stage_missing_validation_block": 18,
            "validate_stage_long_description": 56,
            "isolated_stage_without_commit": 5,
            "reads_from_upstream_without_writes_to": 9,
        }
        baseline = _baseline()

        self.assertEqual(
            sorted(baseline),
            sorted(ceilings),
            "baseline categories changed — add the new category to the "
            "ceilings map in this test (and to _CATEGORY_COMPLIANCE), or "
            "remove the stale one. An uncapped category can grow freely.",
        )

        grown = [
            f"{cat}: {len(baseline[cat])} entries, ceiling {cap}"
            for cat, cap in ceilings.items()
            if len(baseline[cat]) > cap
        ]
        self.assertEqual(
            grown,
            [],
            "baseline grew — a new violation was grandfathered instead of "
            "fixed:\n  " + "\n  ".join(grown) + "\n"
            "Fix the violation. If the growth is genuinely intended, raise "
            "the ceiling in this test in the same commit so the widening is "
            "visible in review.",
        )

    def test_every_baselined_entry_still_names_a_real_stage(self) -> None:
        """A baseline entry pointing at a deleted file or stage is stale.

        Resolves each category against ITS OWN iterator from
        ``_CATEGORY_COMPLIANCE`` rather than against a single stage list.
        Categories do not all key by stage: the reads_from contract category
        keys by ``stage->upstream``, because a stage can read from several
        upstreams and be wrong about only one. Checking those keys against a
        set of bare stage names reports every one of them as a deleted stage.
        """
        stale: list[str] = []
        for category, entries in _baseline().items():
            self.assertIn(
                category,
                _CATEGORY_COMPLIANCE,
                f"baseline category {category!r} has no entry in "
                "_CATEGORY_COMPLIANCE, so its keys cannot be resolved. "
                "test_every_baselined_entry_is_still_a_violation reports this "
                "as the ratchet bypass it is; failing here first would only "
                "raise a confusing KeyError.",
            )
            iterate, _ = _CATEGORY_COMPLIANCE[category]
            known = {
                _stage_key(path, item.get("name")) for path, item in iterate()
            }
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

    def test_every_baselined_entry_is_still_a_violation(self) -> None:
        """A baselined stage that has since been fixed must be removed.

        The deleted-stage check above only catches a baseline entry whose
        file or stage disappeared. It says nothing about a stage that still
        exists but no longer breaks the rule it was grandfathered for — that
        entry is just as stale, and left alone the baseline can only shrink
        by deletion, never by the repair the ratchet exists to reward. This
        recomputes each category's own compliance predicate (the same one
        the live gate above uses, via ``_CATEGORY_COMPLIANCE``) against the
        stage the entry names, so the two checks cannot silently disagree.
        """
        unknown = sorted(set(_baseline()) - set(_CATEGORY_COMPLIANCE))
        self.assertEqual(
            unknown,
            [],
            "baseline declares categories with no compliance predicate: "
            f"{unknown}. Such a category is never recomputed here and is "
            "consulted by no live gate, so violations moved into it are "
            "grandfathered permanently — the ratchet can be bypassed simply "
            "by inventing a category name. Add the category to "
            "_CATEGORY_COMPLIANCE alongside the gate that enforces it, or "
            "delete it from shipped_catalog_baseline.json.",
        )

        stale: list[str] = []
        for category, entries in _baseline().items():
            iterate, is_compliant = _CATEGORY_COMPLIANCE[category]
            by_key = {_stage_key(path, stage.get("name")): stage for path, stage in iterate()}
            for entry in sorted(entries):
                stage = by_key.get(entry)
                if stage is not None and is_compliant(stage):
                    stale.append(f"{category}: {entry}")
        self.assertEqual(
            stale,
            [],
            "baseline entries no longer represent a violation — the stage "
            "was fixed but stays grandfathered, so the ratchet never forces "
            "its removal. Delete these lines from "
            "shipped_catalog_baseline.json:\n  " + "\n  ".join(stale),
        )


# A trigger-param guard inside stage text: `--check 'name=regex'`. A line that
# also carries `--top-level` checks a field of some other JSON document, not a
# trigger param, so it is excluded.
_STAGE_CHECK_RE = re.compile(r"--check '([A-Za-z_]\w*)=([^']*)'", re.ASCII)


def _stage_param_checks(path: Path) -> Iterator[tuple[str, str]]:
    """Yield (name, pattern) for every in-stage trigger-param check in *path*."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if "--top-level" in line:
            continue
        yield from _STAGE_CHECK_RE.findall(line)


class TestStageChecksMatchEngineRules(unittest.TestCase):
    """An in-stage `check-params` pattern must equal the engine rule it repeats.

    The engine enforces `trigger.param_rules` at compile time; stages keep
    their own `check-params` calls as defence in depth. The two copies are
    hand-maintained text, so without this test one can be loosened while the
    other still reads as the boundary.
    """

    def test_stage_checks_equal_engine_rules(self) -> None:
        drift: list[str] = []
        compared = 0
        for path in _catalog_files():
            if _is_fragment(_load_raw(path)):
                continue
            rules: dict[str, set[str]] = {}
            for check in parse_workflow(path).trigger.rules.checks:
                rules.setdefault(check.name, set()).add(check.pattern)
            for name, pattern in _stage_param_checks(path):
                if name not in rules:
                    continue
                compared += 1
                if pattern not in rules[name]:
                    drift.append(f"{path.relative_to(REPO_ROOT)}: {name}")
        self.assertGreater(compared, 0, "no in-stage checks compared; the scan is broken")
        self.assertEqual(drift, [], "in-stage --check pattern differs from trigger.param_rules")

    def test_scan_skips_top_level_and_reads_trigger_checks(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.yaml"
            probe.write_text(
                "x --check 'a=[0-9]+' --check 'b=x'\n"
                "y --top-level --check 'limit=[0-9]+'\n",
                encoding="utf-8",
            )
            self.assertEqual(list(_stage_param_checks(probe)), [("a", "[0-9]+"), ("b", "x")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
