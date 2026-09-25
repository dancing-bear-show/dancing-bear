"""Tests for workflow placeholder rendering.

Design:
  - ``{name}`` matching a trigger param is substituted with the param's value.
  - Unknown ``{name}`` placeholders are left as-is.
  - Braces are never unescaped — ``{{`` and ``}}`` render verbatim.
  - Natural nested JSON is never corrupted (regression guard).

Criteria param resolution:
  - Trigger params inside validation criteria are resolved at compile time.
  - A criterion with exactly one pipe-valued param is expanded: each pipe item
    is substituted into the criterion's prefix/suffix, producing N criteria.
  - A criterion with zero or two-or-more pipe-valued params is kept whole.

Lint checks:
  - The linter warns when a stage description contains ``{{`` outside a
    backtick span that is not a Go-template or GitHub-Actions pattern.
  - The undeclared-variable checker skips ``{ref}`` inside backtick spans,
    so code examples do not produce false-positive warnings.
"""

from __future__ import annotations

import unittest

from workflow.compiler import compile_workflow, resolve_params
from workflow.linter_types import LintWarning
from workflow.models import (
    StageKind,
    ValidationStrategy,
)

from tests.workflow_tests.helpers.factories import (
    make_stage_spec,
    make_trigger_spec,
    make_validation_spec,
    make_workflow_definition,
)


# ---------------------------------------------------------------------------
# resolve_params: param substitution, verbatim braces, no unescape
# ---------------------------------------------------------------------------


class TestResolveParamsVerbatimBraces(unittest.TestCase):
    """resolve_params does NOT unescape doubled braces."""

    def test_nested_json_unchanged(self) -> None:
        """Nested JSON with natural }} at end is returned unchanged."""
        text = '{"a": {"b": 1}}'
        self.assertEqual(resolve_params(text, {}), text)

    def test_double_open_renders_verbatim(self) -> None:
        """{{ is left as {{ — not converted to {."""
        self.assertEqual(resolve_params("{{", {}), "{{")

    def test_double_close_renders_verbatim(self) -> None:
        """}} is left as }} — not converted to }."""
        self.assertEqual(resolve_params("}}", {}), "}}")

    def test_param_substitution_still_works(self) -> None:
        """{key} matching a param is replaced."""
        self.assertEqual(resolve_params("{key}", {"key": "val"}), "val")

    def test_unknown_placeholder_unchanged(self) -> None:
        """An unknown {name} placeholder is left as-is."""
        self.assertEqual(resolve_params("{unknown}", {}), "{unknown}")

    def test_single_braces_unchanged_no_params(self) -> None:
        """Natural single-brace JSON is left unchanged when there are no params."""
        text = '{"a": 1}'
        self.assertEqual(resolve_params(text, {}), text)

    def test_fan_out_placeholder_survives(self) -> None:
        """{fan_out.key} is not a valid identifier — stays as-is."""
        self.assertEqual(
            resolve_params("Process {fan_out.key} now", {}),
            "Process {fan_out.key} now",
        )

    def test_workspace_placeholder_survives(self) -> None:
        """{workspace}/foo is not a trigger param — stays as-is."""
        self.assertEqual(resolve_params("{workspace}/foo", {}), "{workspace}/foo")


# ---------------------------------------------------------------------------
# Compiled descriptions: param substitution in stages
# ---------------------------------------------------------------------------


class TestCompiledDescriptionParamSubstitution(unittest.TestCase):
    """Compiled stage descriptions have trigger params substituted."""

    def test_param_replaced_in_description(self) -> None:
        stage = make_stage_spec(
            name="s",
            description="Hello {name}",
        )
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params={"name": "world"}),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        self.assertEqual(manifest.resolved_stages["s"].spec.description, "Hello world")

    def test_double_braces_stay_doubled_in_description(self) -> None:
        """{{...}} in description is not unescaped — renders verbatim."""
        stage = make_stage_spec(
            name="s",
            description='{{"a": 1}}',
        )
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params={}),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        self.assertEqual(manifest.resolved_stages["s"].spec.description, '{{"a": 1}}')

    def test_natural_nested_json_not_corrupted(self) -> None:
        """Natural nested JSON in a description is not corrupted by compilation."""
        desc = '{"data": {"guide": "x"}}'
        stage = make_stage_spec(name="s", description=desc)
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params={}),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        self.assertEqual(manifest.resolved_stages["s"].spec.description, desc)


# ---------------------------------------------------------------------------
# Criteria param resolution and pipe-split
# ---------------------------------------------------------------------------


class TestValidationCriteriaParamResolution(unittest.TestCase):
    """Trigger params inside validation criteria are resolved at compile time."""

    def _compile_with_criteria(
        self,
        raw_criteria: tuple[str, ...],
        params: dict[str, str],
    ) -> tuple[str, ...]:
        spec = make_validation_spec(
            strategy=ValidationStrategy.unit,
            criteria=raw_criteria,
        )
        stage = make_stage_spec(
            name="vtr-validate",
            kind=StageKind.validate,
            validation=spec,
        )
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params=params),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        resolved_validation = manifest.resolved_stages["vtr-validate"].spec.validation
        self.assertIsNotNone(resolved_validation)
        assert resolved_validation is not None  # nosec B101 - type narrowing for static analysis
        return resolved_validation.criteria

    def test_simple_param_resolved_in_criterion(self) -> None:
        """Pipe-valued param expands by substituting each item into the criterion template."""
        criteria = self._compile_with_criteria(
            raw_criteria=("All criteria in {validation_criteria} are checked",),
            params={"validation_criteria": "counts match|no fabricated numbers"},
        )
        # Each pipe item is substituted INTO the criterion's prefix/suffix.
        self.assertIn("All criteria in counts match are checked", criteria)
        self.assertIn("All criteria in no fabricated numbers are checked", criteria)
        self.assertNotIn("All criteria in {validation_criteria} are checked", criteria)
        # The rendered literal '|' must not appear in any criterion.
        self.assertFalse(any("|" in c for c in criteria))

    def test_criterion_literal_pipe_with_non_pipe_param_stays_whole(self) -> None:
        """A literal '|' in the criterion text with a non-pipe param stays as one criterion."""
        criteria = self._compile_with_criteria(
            raw_criteria=("Use git log | grep {filter_expr} to search",),
            params={"filter_expr": "fix"},
        )
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0], "Use git log | grep fix to search")

    def test_two_pipe_valued_params_stay_whole(self) -> None:
        """When two pipe-valued params are in one criterion, no expansion is done."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{param_a} and {param_b} must pass",),
            params={
                "param_a": "check1|check2",
                "param_b": "verify1|verify2",
            },
        )
        # No cross-multiply: the criterion is kept whole with | values substituted.
        self.assertEqual(len(criteria), 1)
        self.assertIn("check1|check2", criteria[0])
        self.assertIn("verify1|verify2", criteria[0])

    def test_pipe_separated_param_splits_into_multiple_criteria(self) -> None:
        """{param} with pipe-separated value splits into N criteria."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{validation_criteria}",),
            params={"validation_criteria": "criterion A|criterion B|criterion C"},
        )
        self.assertEqual(len(criteria), 3)
        self.assertIn("criterion A", criteria)
        self.assertIn("criterion B", criteria)
        self.assertIn("criterion C", criteria)

    def test_non_pipe_param_stays_as_single_criterion(self) -> None:
        """A param value with no pipes remains a single criterion."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{validation_criteria}",),
            params={"validation_criteria": "exactly one criterion"},
        )
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0], "exactly one criterion")

    def test_empty_pipe_segments_are_dropped(self) -> None:
        """Empty segments from pipe-split are removed."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{validation_criteria}",),
            params={"validation_criteria": "a||b| |c"},
        )
        self.assertEqual(len(criteria), 3)
        self.assertIn("a", criteria)
        self.assertIn("b", criteria)
        self.assertIn("c", criteria)

    def test_unresolved_param_criterion_stays_literal(self) -> None:
        """A criterion with an unknown param is left as-is (no split)."""
        criteria = self._compile_with_criteria(
            raw_criteria=("All {unknown_param} checked",),
            params={},
        )
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0], "All {unknown_param} checked")

    def test_double_braces_in_criterion_stay_doubled(self) -> None:
        """{{literal}} in a criterion stays as {{literal}} — braces are not unescaped."""
        criteria = self._compile_with_criteria(
            raw_criteria=('{{"key": "value"}}',),
            params={},
        )
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0], '{{"key": "value"}}')

    def test_uppercase_pipe_param_expands_to_n_criteria(self) -> None:
        """An uppercase param name like {CRITERIA} is recognised and pipe-expanded."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{CRITERIA}",),
            params={"CRITERIA": "check one|check two|check three"},
        )
        self.assertEqual(len(criteria), 3)
        self.assertIn("check one", criteria)
        self.assertIn("check two", criteria)
        self.assertIn("check three", criteria)

    def test_json_wrapper_kept_per_expansion_item(self) -> None:
        """A criterion like '{"value": {validation_criteria}}' expands with the JSON frame intact."""
        criteria = self._compile_with_criteria(
            raw_criteria=('{"value": {validation_criteria}}',),
            params={"validation_criteria": "alpha|beta"},
        )
        self.assertEqual(len(criteria), 2)
        self.assertIn('{"value": alpha}', criteria)
        self.assertIn('{"value": beta}', criteria)

    def test_double_braced_param_not_pipe_expanded(self) -> None:
        """{{validation_criteria}} is not recognised as a param reference; no pipe expansion."""
        criteria = self._compile_with_criteria(
            raw_criteria=("{{validation_criteria}}",),
            params={"validation_criteria": "item one|item two"},
        )
        # Not expanded — stays as a single criterion.
        self.assertEqual(len(criteria), 1)


# ---------------------------------------------------------------------------
# Domain-recommender integration: the real validate-then-render fragment
# ---------------------------------------------------------------------------


class TestValidateThenRenderFragment(unittest.TestCase):
    """validate-then-render's criterion resolves validation_criteria pipe-param."""

    def test_criteria_expanded_from_pipe_separated_param(self) -> None:
        """Compile the validate stage with a pipe-separated validation_criteria param.

        validate-then-render now uses '{validation_criteria}' (bare param) so each
        pipe item becomes its own standalone criterion.
        """
        spec = make_validation_spec(
            strategy=ValidationStrategy.unit,
            criteria=(
                "Every quantitative claim traces to a source file in the workspace",
                "{validation_criteria}",
            ),
        )
        stage = make_stage_spec(
            name="vtr-validate",
            kind=StageKind.validate,
            validation=spec,
        )
        params = {
            "validation_criteria": "counts match source|no fabricated numbers|all paths exist",
        }
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params=params),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        resolved_validation = manifest.resolved_stages["vtr-validate"].spec.validation
        self.assertIsNotNone(resolved_validation)
        assert resolved_validation is not None  # nosec B101 - type narrowing for static analysis
        criteria = resolved_validation.criteria

        self.assertIn(
            "Every quantitative claim traces to a source file in the workspace",
            criteria,
        )
        # Each pipe item becomes a bare standalone criterion.
        self.assertIn("counts match source", criteria)
        self.assertIn("no fabricated numbers", criteria)
        self.assertIn("all paths exist", criteria)
        self.assertNotIn("{validation_criteria}", criteria)
        # No raw | should appear in any criterion.
        self.assertFalse(any("|" in c for c in criteria))


# ---------------------------------------------------------------------------
# Lint check: escape-style {{ warning
# ---------------------------------------------------------------------------


class TestEscapeStyleBracesLintWarning(unittest.TestCase):
    """The linter warns when a description contains {{ outside exempt patterns."""

    def _lint_stages(self, stages: list[object]) -> list[LintWarning]:
        from workflow.linter import _check_escape_style_braces
        from workflow.linter_types import LintResult

        result: LintResult = LintResult(file="test")
        _check_escape_style_braces(tuple(stages), result)
        return result.warnings

    def test_escape_style_json_warns(self) -> None:
        """{{"key": "val"}} fires the lint warning."""
        stage = make_stage_spec(name="s", description='{{"key": "val"}}')
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 1)
        self.assertIn("does not unescape", warnings[0].message)

    def test_standalone_double_open_warns(self) -> None:
        """A bare {{ on its own fires the lint warning."""
        stage = make_stage_spec(name="s", description="start\n  {{\n    x")
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 1)

    def test_go_template_no_warn(self) -> None:
        """{{.Names}} is a Go template — no warning."""
        stage = make_stage_spec(name="s", description="docker --format '{{.Names}}'")
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 0)

    def test_github_actions_no_warn(self) -> None:
        """${{ secrets.TOKEN }} is GitHub Actions — no warning."""
        stage = make_stage_spec(name="s", description="uses ${{ secrets.TOKEN }}")
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 0)

    def test_backtick_span_no_warn(self) -> None:
        """{{ inside a backtick code span is exempt."""
        stage = make_stage_spec(name="s", description="write `{{` for escaped braces")
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 0)

    def test_natural_nested_json_no_warn(self) -> None:
        """Natural nested JSON with }} at line end does not trigger {{ warning."""
        stage = make_stage_spec(name="s", description='{"data": {"guide": "x"}}')
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 0)

    def test_no_description_no_warn(self) -> None:
        """A stage with no description does not warn."""
        stage = make_stage_spec(name="s", description=None)
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 0)

    def test_one_warning_per_stage(self) -> None:
        """Multiple {{ occurrences in a stage emit only one warning."""
        stage = make_stage_spec(
            name="s",
            description='{{"a": 1}}\n{{"b": 2}}',
        )
        warnings = self._lint_stages([stage])
        self.assertEqual(len(warnings), 1)


# ---------------------------------------------------------------------------
# Undeclared-variable lint: backtick-span exemption
# ---------------------------------------------------------------------------


class TestUndeclaredVarLintBacktickExemption(unittest.TestCase):
    """The undeclared-variable checker skips {ref} inside backtick code spans."""

    def _check_var_warnings(
        self,
        description: str,
        declared_params: dict[str, str] | None = None,
    ) -> list[str]:
        """Return all undeclared-variable warning messages for *description*."""
        from workflow.linter import _check_var_refs
        from workflow.linter_types import LintResult

        stage = make_stage_spec(name="s", description=description)
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params=declared_params or {}),
            stages=(stage,),
        )
        result: LintResult = LintResult(file="test")
        _check_var_refs(wf, result)
        return [w.message for w in result.warnings if "undeclared" in w.message.lower()]

    def test_backtick_var_no_undeclared_warning(self) -> None:
        """{pkg} inside a backtick span is not flagged as undeclared."""
        warnings = self._check_var_warnings(
            description="importlib.import_module(f\"`{pkg}`.meta\")",
            declared_params={},
        )
        self.assertFalse(any("pkg" in w for w in warnings))

    def test_bare_undeclared_var_still_warns(self) -> None:
        """A bare {undeclared} outside backticks still produces a warning."""
        warnings = self._check_var_warnings(
            description="Process {undeclared} items",
            declared_params={},
        )
        self.assertTrue(any("undeclared" in w for w in warnings))

    def test_declared_param_in_backticks_resolves_at_compile_time(self) -> None:
        """resolve_params substitutes a declared param even when it is inside backticks.

        The linter's backtick exemption applies only to _extract_var_refs (the
        undeclared-variable check); it has no effect on resolve_params, which
        substitutes regardless of backtick context.
        """
        from workflow.compiler import resolve_params

        result = resolve_params("Use `{pkg}` module", {"pkg": "mail"})
        self.assertEqual(result, "Use `mail` module")

    def test_declared_param_outside_backticks_no_warning(self) -> None:
        """A {param} that IS declared in trigger.params does not warn."""
        warnings = self._check_var_warnings(
            description="Check {filter_expr} against the index",
            declared_params={"filter_expr": "fix"},
        )
        self.assertFalse(any("filter_expr" in w for w in warnings))

    def test_both_backtick_and_bare_vars_mixed(self) -> None:
        """Backtick-quoted var skipped; bare undeclared var still warns."""
        warnings = self._check_var_warnings(
            description="Run `{pkg}` to produce {undeclared_output}",
            declared_params={},
        )
        # {pkg} inside backtick → no warning for pkg
        self.assertFalse(any("pkg" in w for w in warnings))
        # {undeclared_output} outside backtick → warning
        self.assertTrue(any("undeclared_output" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
