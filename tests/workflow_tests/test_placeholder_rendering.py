"""Tests for workflow placeholder rendering fixes.

Defect 1 — doubled braces render literally:
  After trigger-param substitution, ``{{`` -> ``{`` and ``}}`` -> ``}``
  using str.format-style escaping. Unknown ``{name}`` stays literal.

Defect 2 — trigger params not resolved inside validation criteria:
  A kind:validate stage whose criteria reference a trigger param gets them
  resolved at compile time. A criterion that came from a pipe-separated param
  value is split into one criterion per ``|``-delimited item.

Additional invariants:
  - Fan-out key placeholders survive (they are filled later by the orchestrator)
  - The synthesize-workflow escape instruction renders with ``{{``/``}}``
"""

from __future__ import annotations

import unittest

from workflow.compiler import compile_workflow, resolve_params
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
# Defect 1: doubled-brace unescape
# ---------------------------------------------------------------------------


class TestResolveParamsDoubledBraceUnescape(unittest.TestCase):
    """resolve_params unescapes doubled braces after param substitution."""

    def test_double_open_becomes_single(self) -> None:
        result = resolve_params('{"a": 1}', {})
        # single braces are unchanged (no param key matches)
        self.assertEqual(result, '{"a": 1}')

    def test_doubled_open_becomes_single(self) -> None:
        result = resolve_params('{{"a": 1}}', {})
        self.assertEqual(result, '{"a": 1}')

    def test_four_braces_become_double(self) -> None:
        """{{{{ -> {{ after unescape."""
        result = resolve_params('{{{{', {})
        self.assertEqual(result, '{{')

    def test_four_close_braces_become_double(self) -> None:
        """}}}} -> }} after unescape."""
        result = resolve_params('}}}}', {})
        self.assertEqual(result, '}}')

    def test_unknown_single_brace_stays_literal(self) -> None:
        """An unknown {name} placeholder is left as-is."""
        result = resolve_params('{unknown}', {})
        self.assertEqual(result, '{unknown}')

    def test_known_param_replaced_before_unescape(self) -> None:
        """Param substitution happens first, then brace unescape."""
        result = resolve_params('{key} + {{literal}}', {'key': 'VALUE'})
        self.assertEqual(result, 'VALUE + {literal}')

    def test_unescape_does_not_affect_already_unresolved_single_braces(self) -> None:
        """Single braces that are not params pass through unchanged."""
        result = resolve_params('{workspace}/foo', {})
        self.assertEqual(result, '{workspace}/foo')

    def test_mixed_escape_and_param(self) -> None:
        """JSON example with param: {{"key": "{name}"}} -> {"key": "Alice"}."""
        result = resolve_params('{{"key": "{name}"}}', {'name': 'Alice'})
        self.assertEqual(result, '{"key": "Alice"}')


class TestDoubledBraceInCompiledDescription(unittest.TestCase):
    """Compiled stage descriptions also have their doubled braces unescaped."""

    def test_stage_description_brace_unescape(self) -> None:
        stage = make_stage_spec(
            name="s",
            description='{{"a": 1}}',
        )
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params={}),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        resolved = manifest.resolved_stages["s"]
        self.assertEqual(resolved.spec.description, '{"a": 1}')

    def test_four_braces_in_description_become_double(self) -> None:
        """{{{{text}}}} in YAML description -> {{text}} in rendered description."""
        stage = make_stage_spec(
            name="s",
            description="Escape {{{{",
        )
        wf = make_workflow_definition(
            trigger=make_trigger_spec(source="manual", params={}),
            stages=(stage,),
        )
        manifest = compile_workflow(wf)
        resolved = manifest.resolved_stages["s"]
        self.assertEqual(resolved.spec.description, "Escape {{")


class TestFanOutKeyPlaceholderSurvives(unittest.TestCase):
    """A fan-out key placeholder ({fan_out.key}) must survive unescape unchanged."""

    def test_fan_out_placeholder_is_not_corrupted(self) -> None:
        """Single-brace {fan_out.key} stays literal after resolve_params."""
        result = resolve_params("Process {fan_out.key} now", {})
        # {fan_out.key} is not a valid identifier (contains dot), stays as-is
        self.assertEqual(result, "Process {fan_out.key} now")


# ---------------------------------------------------------------------------
# Defect 2: criteria param resolution and pipe-split
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
        """A criterion referencing {key} has the param substituted.

        The resolved criterion is split on ``|``.  Surrounding template text
        lands in the first and last segments.
        """
        criteria = self._compile_with_criteria(
            raw_criteria=("All criteria in {validation_criteria} are checked",),
            params={"validation_criteria": "counts match|no fabricated numbers"},
        )
        # After resolution + pipe-split:
        #   "All criteria in counts match|no fabricated numbers are checked"
        #   -> ("All criteria in counts match", "no fabricated numbers are checked")
        self.assertIn("All criteria in counts match", criteria)
        self.assertIn("no fabricated numbers are checked", criteria)
        # Original placeholder criterion is replaced
        self.assertNotIn("All criteria in {validation_criteria} are checked", criteria)

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
        # Empty and whitespace-only segments dropped
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

    def test_doubled_braces_in_criterion_unescape(self) -> None:
        """{{literal}} in a criterion unescapes to {literal}."""
        criteria = self._compile_with_criteria(
            raw_criteria=('{{"key": "value"}}',),
            params={},
        )
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0], '{"key": "value"}')


# ---------------------------------------------------------------------------
# Domain-recommender integration: the real validate-then-render fragment
# ---------------------------------------------------------------------------


class TestValidateThenRenderFragment(unittest.TestCase):
    """validate-then-render's criterion resolves validation_criteria pipe-param."""

    def test_criteria_expanded_from_pipe_separated_param(self) -> None:
        """Compile the validate stage with a pipe-separated validation_criteria param."""
        spec = make_validation_spec(
            strategy=ValidationStrategy.unit,
            criteria=(
                "Every quantitative claim traces to a source file in the workspace",
                "All criteria in {validation_criteria} are checked",
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

        # The static criterion survives unchanged
        self.assertIn(
            "Every quantitative claim traces to a source file in the workspace",
            criteria,
        )
        # "All criteria in {validation_criteria} are checked" with
        # validation_criteria = "counts match source|no fabricated numbers|all paths exist"
        # resolves to "All criteria in counts match source|no fabricated numbers|all paths exist are checked"
        # then splits on "|":
        self.assertIn("All criteria in counts match source", criteria)
        self.assertIn("no fabricated numbers", criteria)
        self.assertIn("all paths exist are checked", criteria)
        # The template placeholder criterion is gone
        self.assertNotIn(
            "All criteria in {validation_criteria} are checked",
            criteria,
        )


if __name__ == "__main__":
    unittest.main()
