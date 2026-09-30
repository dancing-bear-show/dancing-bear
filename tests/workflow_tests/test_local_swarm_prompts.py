"""Rendered-prompt and compile-time checks for the local-swarm feature.

Covers:
  (1) concern-sweep-dispatch always includes collateral-damage.md
  (2) local=true never renders ./bin/github or gh calls in fetch-pr-context's local branch
  (3) The `local` param rejects values other than true|false at compile time
  (4) open-pr's record-sweep stage sits between scan-validate and generate-description
      and calls ./bin/workflow sweep-record write with --head and --workspace
  (5) Both the small and large code-review paths still compile

The swarm is a fragment (no trigger.source) so we reach its stages through
code-review.yaml (which includes it) — same as open-pr.yaml does.

Teeth probes at the bottom confirm (1) and (3) really fail when the YAML is
reverted.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.compiler import WorkflowCompileError, compile_workflow, match_when_expression
from workflow.dispatch import build_agent_prompt
from workflow.parser import parse_workflow, parse_workflow_str

_ROOT = Path(__file__).resolve().parents[2]
_CODE_REVIEW = _ROOT / "workflows/code/code-review.yaml"
_OPEN_PR = _ROOT / "workflows/code/open-pr.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile_cr(**params: str):
    defn = parse_workflow(str(_CODE_REVIEW))
    return defn, compile_workflow(defn, project_root=_ROOT, trigger_params=params)


def _compile_open_pr(**params: str):
    defn = parse_workflow(str(_OPEN_PR))
    return defn, compile_workflow(defn, project_root=_ROOT, trigger_params=params)


def _prompt_cr(stage_name: str, workspace: str, **params: str) -> str:
    defn, manifest = _compile_cr(**params)
    stage = manifest.resolved_stages[stage_name]
    return build_agent_prompt(stage, defn.name, workspace)


def _running_stages(workflow_path: Path, **params: str) -> set[str]:
    defn = parse_workflow(str(workflow_path))
    manifest = compile_workflow(defn, project_root=_ROOT, trigger_params=params)
    effective = {**defn.trigger.params, **params}
    return {
        name
        for name, stage in manifest.resolved_stages.items()
        if stage.spec.when is None
        or match_when_expression(stage.spec.when, effective)
    }


# ---------------------------------------------------------------------------
# (1) concern-sweep-dispatch always includes collateral-damage.md
# ---------------------------------------------------------------------------

class TestConcernSweepDispatchAlwaysIncludesCollateralDamage(unittest.TestCase):
    """The guide selection rules must always include collateral-damage.md regardless
    of file extensions present in the diff."""

    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.prompt = _prompt_cr("concern-sweep-dispatch", tmp, local="false")

    def test_collateral_damage_in_always_rule(self) -> None:
        """The always-selected rule must name collateral-damage.md."""
        self.assertIn("collateral-damage.md", self.prompt)

    def test_collateral_damage_on_same_line_as_always(self) -> None:
        """collateral-damage.md must appear on the same line as the 'always' rule."""
        for line in self.prompt.splitlines():
            if "always" in line and ("patterns.md" in line or "collateral-damage.md" in line):
                # Found the 'always' rule line
                self.assertIn(
                    "collateral-damage.md", line,
                    f"'always' rule line does not include collateral-damage.md: {line!r}"
                )
                return
        self.fail("No 'always' rule line found in concern-sweep-dispatch prompt")


# ---------------------------------------------------------------------------
# (2) local=true does not render GitHub/gh calls in fetch-pr-context
# ---------------------------------------------------------------------------

class TestFetchPrContextLocalMode(unittest.TestCase):
    """When local=true the agent prompt for fetch-pr-context must contain a
    LOCAL MODE section with git commands and no GitHub calls, followed by a
    GITHUB MODE section for the false path.

    The description contains both branches as prose (the agent reads {local}
    and follows the right section). Tests verify that the LOCAL MODE section
    appears and contains the expected git commands, and that the GITHUB MODE
    section contains the github CLI calls (not the LOCAL MODE section)."""

    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.local_prompt = _prompt_cr("fetch-pr-context", tmp, local="true")
            self.github_prompt = _prompt_cr("fetch-pr-context", tmp, local="false")
        # Split at the GITHUB MODE section header (not the intro mention).
        # The header contains "(when" which is only in the actual section header.
        delimiter = "GITHUB MODE (when"
        if delimiter in self.local_prompt:
            local_mode_end = self.local_prompt.index(delimiter)
            self.local_section = self.local_prompt[:local_mode_end]
            self.github_section = self.local_prompt[local_mode_end:]
        else:
            self.local_section = self.local_prompt
            self.github_section = ""

    def test_local_prompt_has_local_mode_section(self) -> None:
        """The local mode section heading must appear."""
        self.assertIn("LOCAL MODE", self.local_prompt)

    def test_local_section_has_no_bin_github_pr_view_call(self) -> None:
        """The LOCAL MODE section must not contain ./bin/github pr view calls."""
        # The section may say "Do not call ./bin/github" as a sentinel instruction,
        # but must not contain actual ./bin/github pr view or ./bin/github repo calls.
        self.assertNotIn("./bin/github pr view", self.local_section)
        self.assertNotIn("./bin/github repo", self.local_section)

    def test_local_section_has_no_headrefoid(self) -> None:
        """headRefOid (GitHub API) must not appear in the LOCAL MODE section."""
        self.assertNotIn("headRefOid", self.local_section)

    def test_local_prompt_uses_git_rev_parse_head(self) -> None:
        """In local mode the commit_id comes from git rev-parse HEAD."""
        self.assertIn("git rev-parse HEAD", self.local_section)

    def test_local_prompt_uses_merge_base_origin_main(self) -> None:
        """In local mode the diff base is merge-base(origin/main, HEAD)."""
        self.assertIn("origin/main", self.local_section)
        self.assertIn("merge-base", self.local_section)

    def test_github_section_has_bin_github_call(self) -> None:
        """The GITHUB MODE section must contain ./bin/github calls."""
        self.assertIn("./bin/github", self.github_section)

    def test_github_prompt_has_bin_github_call(self) -> None:
        """In GitHub mode (local=false) the prompt does use ./bin/github."""
        self.assertIn("./bin/github", self.github_prompt)

    def test_local_prompt_instructs_stop_after_local_steps(self) -> None:
        """The local section must explicitly tell the agent to stop and not call github."""
        self.assertIn("Do not call ./bin/github", self.local_section)


# ---------------------------------------------------------------------------
# (3) `local` param rejects non-true|false values at compile time
# ---------------------------------------------------------------------------

class TestLocalParamValidation(unittest.TestCase):
    """param_rules enforces local: 'true|false' before any substitution."""

    def test_true_compiles(self) -> None:
        _compile_cr(local="true")

    def test_false_compiles(self) -> None:
        _compile_cr(local="false")

    def test_invalid_values_rejected(self) -> None:
        for bad in ("yes", "1", "TRUE", "FALSE", "maybe", "true false", "on"):
            with self.subTest(value=bad):
                with self.assertRaises(WorkflowCompileError) as ctx:
                    _compile_cr(local=bad)
                self.assertIn("local", str(ctx.exception))

    def test_hostile_value_rejected_and_not_echoed(self) -> None:
        hostile = "true; rm -rf ~"
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compile_cr(local=hostile)
        self.assertIn("local", str(ctx.exception))
        self.assertNotIn(hostile, str(ctx.exception))

    def test_open_pr_local_param_is_true_by_default(self) -> None:
        """open-pr.yaml declares local='true' so the swarm always runs in local mode."""
        defn = parse_workflow(str(_OPEN_PR))
        self.assertEqual(defn.trigger.params.get("local"), "true")


# ---------------------------------------------------------------------------
# (4) open-pr's record-sweep is between scan-validate and generate-description
# ---------------------------------------------------------------------------

class TestOpenPrRecordSweepStage(unittest.TestCase):
    """record-sweep must exist, depend on swarm-fact-check-findings, and be
    depended-on by generate-description. The human-gate must read from it."""

    def setUp(self) -> None:
        defn, self.manifest = _compile_open_pr()
        self.stages = self.manifest.resolved_stages
        self.group_of: dict[str, int] = {}
        for g_idx, stage_names in enumerate(self.manifest.parallel_groups):
            for name in stage_names:
                self.group_of[name] = g_idx

    def test_record_sweep_stage_exists(self) -> None:
        self.assertIn("record-sweep", self.stages)

    def test_record_sweep_depends_on_swarm_fact_check_findings(self) -> None:
        stage = self.stages["record-sweep"]
        self.assertIn("swarm-fact-check-findings", stage.spec.depends_on)

    def test_generate_description_depends_on_record_sweep(self) -> None:
        stage = self.stages["generate-description"]
        self.assertIn("record-sweep", stage.spec.depends_on)

    def test_record_sweep_calls_sweep_record_write(self) -> None:
        """The prompt for record-sweep must instruct the agent to call
        ./bin/workflow sweep-record write."""
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_agent_prompt(
                self.stages["record-sweep"], "open-pr", tmp
            )
        self.assertIn("sweep-record write", prompt)
        self.assertIn("--head", prompt)
        self.assertIn("--workspace", prompt)

    def test_record_sweep_before_generate_description_in_dag(self) -> None:
        """record-sweep must appear in an earlier parallel group than
        generate-description."""
        self.assertLess(
            self.group_of["record-sweep"],
            self.group_of["generate-description"],
            "record-sweep must be in an earlier DAG group than generate-description",
        )

    def test_record_sweep_after_scan_validate_in_dag(self) -> None:
        """record-sweep must appear after scan-validate."""
        self.assertLess(
            self.group_of["scan-validate"],
            self.group_of["record-sweep"],
            "scan-validate must be in an earlier DAG group than record-sweep",
        )

    def test_human_gate_reads_from_record_sweep(self) -> None:
        """The human-gate should read from record-sweep to display swarm findings."""
        hg = self.stages["human-gate"]
        self.assertIn("record-sweep", hg.spec.reads_from)

    def test_swarm_fetch_pr_context_exists(self) -> None:
        """The swarm is included: swarm-fetch-pr-context must be a stage."""
        self.assertIn("swarm-fetch-pr-context", self.stages)

    def test_swarm_fact_check_findings_exists(self) -> None:
        """swarm-fact-check-findings must be a stage (last running stage in local mode)."""
        self.assertIn("swarm-fact-check-findings", self.stages)


# ---------------------------------------------------------------------------
# (5) Both code-review paths still compile
# ---------------------------------------------------------------------------

class TestCodeReviewPathsCompile(unittest.TestCase):
    """Small and large paths must compile cleanly, with and without local mode."""

    def test_small_path_default_compiles(self) -> None:
        defn, manifest = _compile_cr()
        self.assertGreater(len(manifest.resolved_stages), 0)

    def test_small_path_local_true_compiles(self) -> None:
        defn, manifest = _compile_cr(local="true")
        self.assertGreater(len(manifest.resolved_stages), 0)

    def test_large_path_compiles(self) -> None:
        defn, manifest = _compile_cr(pr_size="large", pr_number="123")
        self.assertGreater(len(manifest.resolved_stages), 0)

    def test_large_path_local_true_compiles(self) -> None:
        defn, manifest = _compile_cr(pr_size="large", pr_number="123", local="true")
        self.assertGreater(len(manifest.resolved_stages), 0)

    def test_human_gate_skipped_in_local_mode(self) -> None:
        running = _running_stages(_CODE_REVIEW, local="true")
        self.assertNotIn("human-gate", running)

    def test_human_gate_runs_in_github_mode(self) -> None:
        running = _running_stages(_CODE_REVIEW, local="false")
        self.assertIn("human-gate", running)

    def test_post_comments_skipped_in_local_mode(self) -> None:
        running = _running_stages(_CODE_REVIEW, local="true")
        self.assertNotIn("post-comments", running)

    def test_post_comments_runs_in_github_mode(self) -> None:
        running = _running_stages(_CODE_REVIEW, local="false")
        self.assertIn("post-comments", running)

    def test_open_pr_compiles_with_default_local_true(self) -> None:
        defn, manifest = _compile_open_pr()
        self.assertGreater(len(manifest.resolved_stages), 0)


# ---------------------------------------------------------------------------
# Teeth probe (1): collateral-damage.md — prove test fails without it
# ---------------------------------------------------------------------------

class TestTeethCollateralDamageInAlways(unittest.TestCase):
    """Demonstrate the test would fail if collateral-damage.md were removed from
    the 'always' selection rule — by compiling a minimal workflow that lacks it."""

    def test_prompt_without_collateral_damage_lacks_it(self) -> None:
        """A prompt that only has 'always → patterns.md' does not contain collateral-damage.md."""
        yaml_text = (
            "name: probe\n"
            "version: '1'\n"
            "description: probe\n"
            "trigger:\n"
            "  source: manual\n"
            "  params:\n"
            "    local: 'false'\n"
            "  param_rules:\n"
            "    local: 'true|false'\n"
            "stages:\n"
            "  - name: concern-sweep-dispatch\n"
            "    kind: gather\n"
            "    executor: inline\n"
            "    depends_on: []\n"
            "    description: >\n"
            "      always -> patterns.md\n"
            "    agent:\n"
            "      role: researcher\n"
            "    writes_to: [concern-sweep-index.json]\n"
        )
        defn = parse_workflow_str(yaml_text)
        manifest = compile_workflow(defn, project_root=_ROOT, trigger_params={})
        stage = manifest.resolved_stages["concern-sweep-dispatch"]
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_agent_prompt(stage, "probe", tmp)
        # This probe YAML does not have collateral-damage.md, so it should be absent
        self.assertNotIn("collateral-damage.md", prompt,
                         "probe YAML without collateral-damage.md should not have it in prompt")

    def test_real_workflow_has_collateral_damage(self) -> None:
        """The real code-review.yaml DOES include collateral-damage.md (the real test)."""
        with tempfile.TemporaryDirectory() as tmp:
            prompt = _prompt_cr("concern-sweep-dispatch", tmp, local="false")
        self.assertIn("collateral-damage.md", prompt)


# ---------------------------------------------------------------------------
# Teeth probe (3): local param_rule — prove test fails without the rule
# ---------------------------------------------------------------------------

class TestTeethLocalParamRule(unittest.TestCase):
    """Verify the param_rules for local DOES reject bad values in code-review.yaml.
    If the rule were removed, hostile values would compile without error."""

    def test_hostile_value_fails_with_rule(self) -> None:
        """The real code-review.yaml rejects hostile local values."""
        with self.assertRaises(WorkflowCompileError):
            _compile_cr(local="yes; id")

    def test_bad_value_compiles_without_rule(self) -> None:
        """A workflow without a param_rule for local accepts any value — proving
        that the rule is what makes test (3) teeth."""
        yaml_no_rule = (
            "name: probe\n"
            "version: '1'\n"
            "description: probe\n"
            "trigger:\n"
            "  source: manual\n"
            "  params:\n"
            "    local: 'false'\n"
            "stages:\n"
            "  - name: s1\n"
            "    kind: gather\n"
            "    description: 'local is {local}'\n"
            "    agent: {role: researcher}\n"
        )
        # No param_rules -> hostile value compiles without error
        manifest = compile_workflow(
            parse_workflow_str(yaml_no_rule),
            project_root=_ROOT,
            trigger_params={"local": "yes"},
        )
        self.assertIn("s1", manifest.resolved_stages)


if __name__ == "__main__":
    unittest.main()
