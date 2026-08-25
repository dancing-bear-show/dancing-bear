"""Additional coverage tests for workflow.linter.

Targets uncovered lines in the 69.7% baseline:
  - _lint_fragment (happy path + WorkflowParseError path)
  - _fragment_stage_names (prefix matching, no-prefix, no-includes)
  - _build_known_vars (exclusive_fragment_vars vs shared vars)
  - _stage_undeclared_refs (fan_out.key suppression, non-StageSpec input)
  - _check_var_refs (fragment-only vars not warned — see the note above that
    test; the suppression happens in _build_known_vars, not the skip guard)
  - _release_dependents / _bfs_advance (DAG wiring)
  - _check_cli_commands (pattern extraction, dedup, check_commands gate)
  - _cmd_warning (field and stage shape)
  - _validate_cli_command (all subprocess branches, patched, never real)
  - _looks_like_invalid_subcommand (true/false cases)
  - _check_include_files (missing fragment file, entry without path key)
  - lint_workflow OSError branch
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow.linter import (
    LintResult,
    LintWarning,
    _bfs_advance,
    _build_known_vars,
    _check_cli_commands,
    _check_include_files,
    _cmd_warning,
    _fragment_stage_names,
    _looks_like_invalid_subcommand,
    _release_dependents,
    _stage_undeclared_refs,
    _validate_cli_command,
    lint_workflow,
)
from workflow.models import (
    FanOutSpec,
    IncludeSpec,
    TriggerSpec,
    WorkflowDefinition,
)

from tests.workflow_tests.helpers.factories import (
    make_stage_spec,
    make_workflow_definition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_yaml(name: str = "test-wf", extra: str = "") -> str:
    return (
        "name: " + name + "\n"
        "version: \"1.0\"\n"
        "description: Test workflow\n"
        "trigger:\n"
        "  source: manual\n"
        "  params:\n"
        "    team: my-team\n"
        "stages:\n"
        "  - name: gather\n"
        "    kind: gather\n"
        "    description: Gather data for {team}\n"
        "    agent:\n"
        "      role: researcher\n"
        + extra
    )


def _fragment_yaml(valid: bool = True) -> str:
    if valid:
        return (
            "fragment: true\n"
            "stages:\n"
            "  - name: frag-stage\n"
            "    kind: gather\n"
            "    description: Fragment stage\n"
            "    agent:\n"
            "      role: researcher\n"
        )
    return "fragment: true\nstages:\n  - this is not valid\n"


# ---------------------------------------------------------------------------
# lint_workflow -- OSError branch (lines 126-131)
# ---------------------------------------------------------------------------


class TestLintWorkflowOSError(unittest.TestCase):
    def test_oserror_on_read_produces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "wf.yaml"
            wf.write_text(_minimal_yaml(), encoding="utf-8")
            with patch("workflow.linter.Path.read_text", side_effect=OSError("perm")):
                result = lint_workflow(wf)
            self.assertFalse(result.valid)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("cannot read", result.errors[0].message)
            self.assertEqual(result.errors[0].field, "file")
            self.assertEqual(result.errors[0].stage, "<global>")


# ---------------------------------------------------------------------------
# _lint_fragment (lines 173-190)
# ---------------------------------------------------------------------------


class TestLintFragment(unittest.TestCase):
    def test_valid_fragment_returns_stage_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fp = Path(tmp) / "frag.yaml"
            fp.write_text(_fragment_yaml(True), encoding="utf-8")
            result = lint_workflow(fp)
            self.assertTrue(result.valid)
            self.assertEqual(result.stages, 1)
            self.assertEqual(len(result.errors), 0)

    def test_invalid_fragment_returns_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fp = Path(tmp) / "frag.yaml"
            fp.write_text(_fragment_yaml(False), encoding="utf-8")
            result = lint_workflow(fp)
            self.assertFalse(result.valid)
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(result.errors[0].field, "<parse>")
            self.assertEqual(result.errors[0].stage, "<global>")


# ---------------------------------------------------------------------------
# _fragment_stage_names (lines 198-214)
# ---------------------------------------------------------------------------


class TestFragmentStageNames(unittest.TestCase):
    def test_no_includes_returns_empty(self) -> None:
        defn = make_workflow_definition()
        self.assertEqual(_fragment_stage_names(defn), frozenset())

    def test_include_with_empty_prefix_returns_empty(self) -> None:
        inc = IncludeSpec(path="frag.yaml", prefix="")
        stage = make_stage_spec(name="some-stage")
        trigger = TriggerSpec(source="manual")
        defn = WorkflowDefinition(
            name="t", version="1.0", description="t",
            trigger=trigger, stages=(stage,), includes=(inc,),
        )
        self.assertEqual(_fragment_stage_names(defn), frozenset())

    def test_include_with_prefix_matches_prefixed_stages(self) -> None:
        inc = IncludeSpec(path="frag.yaml", prefix="my")
        stage_frag = make_stage_spec(name="my-frag-stage")
        stage_caller = make_stage_spec(name="caller-stage")
        trigger = TriggerSpec(source="manual")
        defn = WorkflowDefinition(
            name="t", version="1.0", description="t",
            trigger=trigger, stages=(stage_frag, stage_caller), includes=(inc,),
        )
        names = _fragment_stage_names(defn)
        self.assertIn("my-frag-stage", names)
        self.assertNotIn("caller-stage", names)

    def test_non_workflow_definition_returns_empty(self) -> None:
        self.assertEqual(_fragment_stage_names(object()), frozenset())


# ---------------------------------------------------------------------------
# _build_known_vars (lines 217-231)
# ---------------------------------------------------------------------------


class TestBuildKnownVars(unittest.TestCase):
    def test_declared_params_always_known(self) -> None:
        trigger = TriggerSpec(source="manual", params={"team": "x", "env": "y"})
        stage = make_stage_spec(name="s", description="use {team}")
        defn = WorkflowDefinition(
            name="t", version="1.0", description="t",
            trigger=trigger, stages=(stage,),
        )
        _, known = _build_known_vars(defn)
        self.assertIn("team", known)
        self.assertIn("env", known)
        self.assertIn("workspace", known)

    def test_exclusive_fragment_vars_added_to_known(self) -> None:
        inc = IncludeSpec(path="frag.yaml", prefix="my")
        trigger = TriggerSpec(source="manual", params={})
        stage_frag = make_stage_spec(name="my-frag-stage", description="uses {fragment_only_var}")
        stage_caller = make_stage_spec(name="caller-stage", description="uses {caller_var}")
        defn = WorkflowDefinition(
            name="t", version="1.0", description="t",
            trigger=trigger, stages=(stage_frag, stage_caller), includes=(inc,),
        )
        _, known = _build_known_vars(defn)
        self.assertIn("fragment_only_var", known)
        self.assertNotIn("caller_var", known)

    def test_shared_var_not_in_exclusive_fragment_vars(self) -> None:
        inc = IncludeSpec(path="frag.yaml", prefix="my")
        trigger = TriggerSpec(source="manual", params={})
        stage_frag = make_stage_spec(name="my-frag-stage", description="uses {shared_var}")
        stage_caller = make_stage_spec(name="caller-stage", description="uses {shared_var}")
        defn = WorkflowDefinition(
            name="t", version="1.0", description="t",
            trigger=trigger, stages=(stage_frag, stage_caller), includes=(inc,),
        )
        _, known = _build_known_vars(defn)
        self.assertNotIn("shared_var", known)


# ---------------------------------------------------------------------------
# _stage_undeclared_refs (lines 234-241)
# ---------------------------------------------------------------------------


class TestStageUndeclaredRefs(unittest.TestCase):
    def test_fan_out_key_suppresses_ref_warning(self) -> None:
        fan_out = FanOutSpec(source="gather", field="items", key="item")
        stage = make_stage_spec(name="s", description="Process {item}", fan_out=fan_out)
        result = _stage_undeclared_refs(stage, frozenset())
        self.assertNotIn("item", result)

    def test_undeclared_var_not_in_fan_out_key_reported(self) -> None:
        fan_out = FanOutSpec(source="gather", field="items", key="item")
        stage = make_stage_spec(name="s", description="Process {item} and {undeclared}", fan_out=fan_out)
        result = _stage_undeclared_refs(stage, frozenset())
        self.assertIn("undeclared", result)
        self.assertNotIn("item", result)

    def test_non_stage_spec_returns_empty(self) -> None:
        self.assertEqual(_stage_undeclared_refs(object(), frozenset({"x"})), [])

    def test_no_fan_out_all_undeclared_reported(self) -> None:
        stage = make_stage_spec(name="s", description="Uses {alpha} and {beta}")
        result = _stage_undeclared_refs(stage, frozenset({"alpha"}))
        self.assertIn("beta", result)
        self.assertNotIn("alpha", result)


# ---------------------------------------------------------------------------
# _release_dependents (lines 308-324)
# ---------------------------------------------------------------------------


class TestReleaseDependents(unittest.TestCase):
    def test_releases_single_dependent(self) -> None:
        deps = {"b": {"a"}, "c": {"b"}}
        in_degree = {"b": 1, "c": 1}
        ready = _release_dependents("a", deps, in_degree)
        self.assertEqual(ready, ["b"])
        self.assertNotIn("b", in_degree)

    def test_no_dependents_returns_empty(self) -> None:
        ready = _release_dependents("x", {"b": {"a"}}, {})
        self.assertEqual(ready, [])

    def test_partial_release_does_not_emit(self) -> None:
        deps = {"c": {"a", "b"}}
        in_degree = {"c": 2}
        ready = _release_dependents("a", deps, in_degree)
        self.assertEqual(ready, [])
        self.assertEqual(in_degree["c"], 1)

    def test_multiple_dependents_released(self) -> None:
        deps = {"b": {"a"}, "c": {"a"}}
        in_degree = {"b": 1, "c": 1}
        ready = _release_dependents("a", deps, in_degree)
        self.assertEqual(sorted(ready), ["b", "c"])


# ---------------------------------------------------------------------------
# _bfs_advance (lines 327-339)
# ---------------------------------------------------------------------------


class TestBfsAdvance(unittest.TestCase):
    def test_advance_processes_wave(self) -> None:
        deps = {"b": {"a"}, "c": {"b"}}
        in_degree = {"b": 1, "c": 1}
        next_q = _bfs_advance(["a"], deps, in_degree)
        self.assertEqual(next_q, ["b"])
        self.assertNotIn("c", next_q)

    def test_advance_empty_queue_returns_empty(self) -> None:
        self.assertEqual(_bfs_advance([], {}, {}), [])

    def test_advance_cleans_up_in_degree_for_queue_members(self) -> None:
        in_degree: dict[str, int] = {"a": 0}
        _bfs_advance(["a"], {}, in_degree)
        self.assertNotIn("a", in_degree)


# ---------------------------------------------------------------------------
# _looks_like_invalid_subcommand (lines 414-417)
# ---------------------------------------------------------------------------


class TestLooksLikeInvalidSubcommand(unittest.TestCase):
    def test_unrecognized_arguments_returns_true(self) -> None:
        self.assertTrue(_looks_like_invalid_subcommand("unrecognized arguments: foo"))

    def test_invalid_choice_returns_true(self) -> None:
        self.assertTrue(_looks_like_invalid_subcommand("invalid choice: bad"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(_looks_like_invalid_subcommand("INVALID CHOICE: bad"))
        self.assertTrue(_looks_like_invalid_subcommand("Unrecognized Arguments: x"))

    def test_normal_output_returns_false(self) -> None:
        self.assertFalse(_looks_like_invalid_subcommand("Usage: mail [options]"))

    def test_empty_string_returns_false(self) -> None:
        self.assertFalse(_looks_like_invalid_subcommand(""))

    def test_generic_error_returns_false(self) -> None:
        self.assertFalse(_looks_like_invalid_subcommand("error: connection refused"))


# ---------------------------------------------------------------------------
# _cmd_warning (lines 381-383)
# ---------------------------------------------------------------------------


class TestCmdWarning(unittest.TestCase):
    def test_warning_shape(self) -> None:
        w = _cmd_warning("my-stage", "some message")
        self.assertIsInstance(w, LintWarning)
        self.assertEqual(w.stage, "my-stage")
        self.assertEqual(w.field, "description")
        self.assertEqual(w.message, "some message")


# ---------------------------------------------------------------------------
# _validate_cli_command (lines 386-411) -- all subprocess paths patched
# ---------------------------------------------------------------------------


class TestValidateCliCommand(unittest.TestCase):
    def test_file_not_found_returns_warning(self) -> None:
        with patch("workflow.linter.subprocess.run", side_effect=FileNotFoundError):
            result = _validate_cli_command("nonexistent", "sub", "stage1")
        self.assertIsNotNone(result)
        assert result is not None  # narrows LintWarning | None for mypy
        self.assertIsInstance(result, LintWarning)
        self.assertIn("command not found", result.message)
        self.assertIn("nonexistent", result.message)

    def test_timeout_returns_skipped_warning(self) -> None:
        with patch(
            "workflow.linter.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=3),
        ):
            result = _validate_cli_command("mail", "labels", "stage1")
        self.assertIsNotNone(result)
        assert result is not None  # narrows LintWarning | None for mypy
        self.assertIn("timeout", result.message)
        self.assertIn("mail labels", result.message)

    def test_oserror_returns_skipped_warning(self) -> None:
        with patch("workflow.linter.subprocess.run", side_effect=OSError("perm")):
            result = _validate_cli_command("mail", "labels", "stage1")
        self.assertIsNotNone(result)
        assert result is not None  # narrows LintWarning | None for mypy
        self.assertIn("OSError", result.message)

    def test_returncode_zero_returns_none(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"Usage: mail [options]"
        mock_proc.stderr = b""
        with patch("workflow.linter.subprocess.run", return_value=mock_proc):
            result = _validate_cli_command("mail", "labels", "stage1")
        self.assertIsNone(result)

    def test_nonzero_with_invalid_choice_returns_warning(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stdout = b""
        mock_proc.stderr = b"invalid choice: badcmd"
        with patch("workflow.linter.subprocess.run", return_value=mock_proc):
            result = _validate_cli_command("mail", "badcmd", "stage1")
        self.assertIsNotNone(result)
        assert result is not None  # narrows LintWarning | None for mypy
        self.assertIn("command not found", result.message)

    def test_nonzero_without_invalid_choice_returns_none(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = b"Error occurred"
        mock_proc.stderr = b"some other error"
        with patch("workflow.linter.subprocess.run", return_value=mock_proc):
            result = _validate_cli_command("mail", "labels", "stage1")
        self.assertIsNone(result)

    def test_allowlisted_sub_missing_bin_returns_warning(self) -> None:
        # docs/search is allowlisted; if bin doesn't exist -> warning, no subprocess call.
        # Path.exists is patched rather than relying on ./bin/docs genuinely being
        # absent: CLAUDE.md reserves `docs` for a planned CLI, so shipping bin/docs
        # would silently flip this test from asserting the missing-bin branch to
        # asserting nothing. The sibling test below patches it True for the same reason.
        with patch("workflow.linter.Path.exists", return_value=False):
            with patch("workflow.linter.subprocess.run") as mock_run:
                result = _validate_cli_command("docs", "search", "stage1")
        mock_run.assert_not_called()
        self.assertIsNotNone(result)
        assert result is not None  # narrows LintWarning | None for mypy
        self.assertIn("command not found", result.message)

    def test_allowlisted_sub_existing_bin_returns_none(self) -> None:
        # Patch Path.exists so the bin appears to exist -> None returned, no subprocess
        with patch("workflow.linter.Path.exists", return_value=True):
            with patch("workflow.linter.subprocess.run") as mock_run:
                result = _validate_cli_command("docs", "search", "stage1")
        mock_run.assert_not_called()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _check_cli_commands (lines 364-378)
# ---------------------------------------------------------------------------


class TestCheckCliCommands(unittest.TestCase):
    def test_valid_command_no_warning(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"Usage: ..."
        mock_proc.stderr = b""
        defn = make_workflow_definition(stages=(
            make_stage_spec(name="s", description="Run ./bin/mail labels to gather data"),
        ))
        result = LintResult(file="test.yaml")
        with patch("workflow.linter.subprocess.run", return_value=mock_proc):
            _check_cli_commands(defn, result)
        self.assertEqual(len(result.warnings), 0)

    def test_invalid_command_adds_warning(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stdout = b""
        mock_proc.stderr = b"invalid choice: badcmd"
        defn = make_workflow_definition(stages=(
            make_stage_spec(name="s", description="Run ./bin/mail badcmd to do stuff"),
        ))
        result = LintResult(file="test.yaml")
        with patch("workflow.linter.subprocess.run", return_value=mock_proc):
            _check_cli_commands(defn, result)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("badcmd", result.warnings[0].message)

    def test_same_command_in_multiple_stages_deduped(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"Usage: ..."
        mock_proc.stderr = b""
        defn = make_workflow_definition(stages=(
            make_stage_spec(name="s1", description="Run ./bin/mail labels first"),
            make_stage_spec(name="s2", description="Also ./bin/mail labels later"),
        ))
        result = LintResult(file="test.yaml")
        with patch("workflow.linter.subprocess.run", return_value=mock_proc) as mock_run:
            _check_cli_commands(defn, result)

        # The probe count is the behaviour under test — two stages naming the
        # same command must be probed once — but pin the observable result too,
        # so the test fails if dedup ever starts swallowing real warnings.
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(result.warnings, [])

    def test_non_workflow_definition_is_noop(self) -> None:
        result = LintResult(file="test.yaml")
        _check_cli_commands(object(), result)
        self.assertEqual(len(result.warnings), 0)


# ---------------------------------------------------------------------------
# _check_include_files (lines 420-435)
# ---------------------------------------------------------------------------


class TestCheckIncludeFiles(unittest.TestCase):
    def test_missing_fragment_file_adds_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "wf.yaml"
            wf.write_text(
                "name: test-wf\nversion: \"1.0\"\ndescription: Test\ntrigger:\n"
                "  source: manual\ninclude:\n  - path: missing-fragment.yaml\n"
                "    prefix: frag\nstages:\n  - name: gather\n    kind: gather\n"
                "    description: Gather\n    agent:\n      role: researcher\n",
                encoding="utf-8",
            )
            result = lint_workflow(wf)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        error = result.errors[0]
        self.assertEqual(error.field, "include")
        self.assertEqual(error.stage, "<global>")
        self.assertIn("fragment file not found", error.message)
        self.assertIn("missing-fragment.yaml", error.message)

    def test_include_entry_without_path_key_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "wf.yaml"
            result = LintResult(file=str(wf))
            text = "name: wf\ninclude:\n  - not-a-dict-entry\n"
            _check_include_files(text, wf, result)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)


# ---------------------------------------------------------------------------
# lint_workflow -- check_commands gate (lines 166-167)
# ---------------------------------------------------------------------------


class TestLintWorkflowCheckCommandsGate(unittest.TestCase):
    def test_check_commands_false_skips_cli_validation(self) -> None:
        extra = (
            "  - name: step\n    kind: execute\n"
            "    description: Run ./bin/mail badcmd here\n"
            "    agent:\n      role: researcher\n    depends_on: [gather]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "wf.yaml"
            wf.write_text(_minimal_yaml(extra=extra), encoding="utf-8")
            with patch("workflow.linter.subprocess.run") as mock_run:
                lint_workflow(wf, check_commands=False)
        mock_run.assert_not_called()

    def test_check_commands_true_calls_subprocess(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"Usage: ..."
        mock_proc.stderr = b""
        extra = (
            "  - name: step\n    kind: execute\n"
            "    description: Run ./bin/mail labels to do something\n"
            "    agent:\n      role: researcher\n    depends_on: [gather]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / "wf.yaml"
            wf.write_text(_minimal_yaml(extra=extra), encoding="utf-8")
            with patch("workflow.linter.subprocess.run", return_value=mock_proc) as mock_run:
                lint_workflow(wf, check_commands=True)
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Fragment-only vars are not warned about.
#
# Note on mechanism: this is suppressed in _build_known_vars, not by the
# `if stage.name in fragment_names: continue` guard in _check_var_refs.
# _build_known_vars folds exclusive_fragment_vars into the known set, so the
# ref never reaches the warning path at all. Disabling that guard does NOT
# make this test fail — verified by mutation — so do not read a passing test
# here as coverage of the guard itself.
# ---------------------------------------------------------------------------


class TestCheckVarRefsFragmentSkip(unittest.TestCase):
    def test_fragment_stage_vars_not_warned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frag = Path(tmp) / "frag.yaml"
            frag.write_text(
                "fragment: true\nstages:\n  - name: frag-stage\n    kind: gather\n"
                "    description: Uses {fragment_only_var}\n    agent:\n      role: researcher\n",
                encoding="utf-8",
            )
            # Written as a literal block rather than concatenated escapes so the
            # YAML structure — and where the fragment path is spliced in — is
            # readable at a glance. Doubled braces escape the f-string so
            # {fragment_only_var} reaches the linter intact.
            wf = Path(tmp) / "wf.yaml"
            wf.write_text(
                f"""name: test-wf
version: "1.0"
description: Test
trigger:
  source: manual
  params:
    team: myteam
include:
  - path: {frag}
    prefix: my
stages:
  - name: my-frag-stage
    kind: gather
    description: Uses {{fragment_only_var}}
    agent:
      role: researcher
""",
                encoding="utf-8",
            )
            result = lint_workflow(wf)

        # The fragment-prefixed stage must not be warned about.
        fov_warnings = [w for w in result.warnings if "fragment_only_var" in w.message]
        self.assertEqual(len(fov_warnings), 0)

        # Asserting only the above is not enough: it also passes when nothing
        # warns for unrelated reasons. Pin the contrast — a NON-fragment stage
        # referencing an undeclared var must still warn, which is what proves
        # the skip is scoped to fragment stages rather than suppressing
        # everything.
        with tempfile.TemporaryDirectory() as tmp2:
            wf2 = Path(tmp2) / "wf.yaml"
            wf2.write_text(
                _minimal_yaml(extra=(
                    "  - name: caller-stage\n"
                    "    kind: gather\n"
                    "    description: Uses {caller_only_var}\n"
                    "    agent:\n"
                    "      role: researcher\n"
                )),
                encoding="utf-8",
            )
            result2 = lint_workflow(wf2)

        caller_warnings = [w for w in result2.warnings if "caller_only_var" in w.message]
        self.assertEqual(len(caller_warnings), 1)


if __name__ == "__main__":
    unittest.main()
