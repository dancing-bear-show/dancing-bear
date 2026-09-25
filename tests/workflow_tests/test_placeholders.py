"""Unit tests for workflow.placeholders.

Grammar:
- {ident} is a placeholder when ident is [A-Za-z_]\w* (ASCII).
- {{ident}} is NOT a placeholder (doubled braces render verbatim).
- {2,40} is NOT a placeholder (not an identifier).
- {name} inside a JSON wrapper such as '{"k": {name}}' IS a placeholder.

Backtick skipping (skip_code=True):
- A {name} inside a backtick code span on the same line is not a ref.

Substitution:
- identifier-shaped keys are replaced; unknown names left as-is.
- non-identifier keys (regex quantifiers) are skipped.
"""

from __future__ import annotations

import unittest

from workflow.placeholders import find_refs, in_backtick_span, is_identifier, substitute


class TestIsIdentifier(unittest.TestCase):
    def test_lowercase(self) -> None:
        self.assertTrue(is_identifier("foo"))

    def test_uppercase(self) -> None:
        self.assertTrue(is_identifier("CRITERIA"))

    def test_mixed_case(self) -> None:
        self.assertTrue(is_identifier("ValidationCriteria"))

    def test_underscore_prefix(self) -> None:
        self.assertTrue(is_identifier("_private"))

    def test_digits_in_body(self) -> None:
        self.assertTrue(is_identifier("param1"))

    def test_digit_prefix_rejected(self) -> None:
        self.assertFalse(is_identifier("1param"))

    def test_comma_rejected(self) -> None:
        self.assertFalse(is_identifier("2,40"))

    def test_space_rejected(self) -> None:
        self.assertFalse(is_identifier("a b"))

    def test_empty_rejected(self) -> None:
        self.assertFalse(is_identifier(""))


class TestFindRefs(unittest.TestCase):
    """find_refs without skip_code."""

    def test_simple_placeholder(self) -> None:
        self.assertEqual(find_refs("{name}"), {"name"})

    def test_uppercase_placeholder(self) -> None:
        self.assertEqual(find_refs("{CRITERIA}"), {"CRITERIA"})

    def test_underscore_placeholder(self) -> None:
        self.assertEqual(find_refs("{validation_criteria}"), {"validation_criteria"})

    def test_double_brace_not_a_ref(self) -> None:
        """{{name}} is not a placeholder — doubled braces render verbatim."""
        self.assertEqual(find_refs("{{name}}"), set())

    def test_double_brace_with_declared_param(self) -> None:
        """{{name}} stays empty even when name would be a valid param."""
        self.assertEqual(find_refs("{{validation_criteria}}"), set())

    def test_json_wrapper_is_a_ref(self) -> None:
        """A {name} followed by } (JSON context) IS a ref."""
        self.assertEqual(find_refs('{"value": {validation_criteria}}'), {"validation_criteria"})

    def test_non_identifier_not_a_ref(self) -> None:
        """Regex quantifiers like {2,40} are not placeholders."""
        self.assertEqual(find_refs("{2,40}"), set())

    def test_multiple_refs(self) -> None:
        refs = find_refs("{foo} and {BAR} and {baz}")
        self.assertEqual(refs, {"foo", "BAR", "baz"})

    def test_double_brace_mixed_with_real_ref(self) -> None:
        """{{x}} is ignored but {y} is found."""
        self.assertEqual(find_refs("{{x}} and {y}"), {"y"})

    def test_empty_text(self) -> None:
        self.assertEqual(find_refs(""), set())

    def test_no_placeholder(self) -> None:
        self.assertEqual(find_refs("plain text with no braces"), set())

    def test_shell_var_not_a_ref(self) -> None:
        """${SAFE} is shell expansion, not a workflow placeholder."""
        self.assertEqual(find_refs("${SAFE}"), set())

    def test_shell_var_mixed_with_workflow_ref(self) -> None:
        """${SHELL} is not a ref but {workflow_param} in the same text is."""
        self.assertEqual(find_refs("${SHELL} and {workflow_param}"), {"workflow_param"})

    def test_dollar_space_brace_still_a_ref(self) -> None:
        """$ {X} (space between $ and {) is still a ref — only ${ (no space) is shell."""
        self.assertEqual(find_refs("$ {X}"), {"X"})

    def test_letter_before_brace_still_a_ref(self) -> None:
        """a{X} — brace preceded by a letter, not $ or { — is still a ref."""
        self.assertEqual(find_refs("a{X}"), {"X"})


class TestFindRefsSkipCode(unittest.TestCase):
    """find_refs with skip_code=True."""

    def test_ref_outside_backticks_found(self) -> None:
        self.assertEqual(find_refs("{name} is a param", skip_code=True), {"name"})

    def test_ref_inside_backticks_skipped(self) -> None:
        self.assertEqual(find_refs("`{pkg}` is a code example", skip_code=True), set())

    def test_ref_after_closed_backtick_found(self) -> None:
        self.assertEqual(find_refs("`{a}` and {b}", skip_code=True), {"b"})

    def test_double_brace_inside_backticks_stays_ignored(self) -> None:
        """{{x}} inside backticks: doubled brace is still not a ref."""
        self.assertEqual(find_refs("`{{x}}`", skip_code=True), set())

    def test_git_reflog_syntax_in_backticks_not_a_ref(self) -> None:
        """HEAD@{N} inside backticks is not a ref with skip_code=True."""
        self.assertEqual(find_refs("use `HEAD@{N}` not HEAD~N", skip_code=True), set())

    def test_git_reflog_syntax_outside_backticks_is_a_ref(self) -> None:
        """HEAD@{N} outside backticks IS a ref (the @ is not a special guard)."""
        self.assertIn("N", find_refs("use HEAD@{N} not HEAD~N", skip_code=False))

    def test_multiline_backtick_scoping(self) -> None:
        """Backtick spans are per-line."""
        text = "`{a}`\n{b}"
        refs = find_refs(text, skip_code=True)
        self.assertNotIn("a", refs)
        self.assertIn("b", refs)


class TestInBacktickSpan(unittest.TestCase):
    def test_outside_span(self) -> None:
        self.assertFalse(in_backtick_span("hello {x}", 6))

    def test_inside_span(self) -> None:
        self.assertTrue(in_backtick_span("`{x}`", 1))

    def test_after_closed_span(self) -> None:
        self.assertFalse(in_backtick_span("`{a}` {b}", 6))


class TestSubstitute(unittest.TestCase):
    def test_simple_substitution(self) -> None:
        self.assertEqual(substitute("{name}", {"name": "Alice"}), "Alice")

    def test_uppercase_key(self) -> None:
        self.assertEqual(substitute("{CRITERIA}", {"CRITERIA": "check one"}), "check one")

    def test_unknown_placeholder_left_as_is(self) -> None:
        self.assertEqual(substitute("{unknown}", {}), "{unknown}")

    def test_non_identifier_key_skipped(self) -> None:
        """Non-identifier keys do not cause {2,40} style patterns to change."""
        self.assertEqual(substitute("{2,40}", {"2,40": "oops"}), "{2,40}")

    def test_double_brace_left_as_is(self) -> None:
        """{{name}} is NOT a placeholder; substitute must leave it untouched even when name is in mapping."""
        result = substitute("{{name}}", {"name": "Alice"})
        self.assertEqual(result, "{{name}}")

    def test_shell_var_left_as_is(self) -> None:
        """${name} is shell expansion, not a workflow placeholder; substitute must leave it untouched."""
        result = substitute("${name}", {"name": "Alice"})
        self.assertEqual(result, "${name}")

    def test_double_brace_with_real_placeholder_nearby(self) -> None:
        """{{name}} stays literal while {other} is substituted."""
        result = substitute("{{name}} and {other}", {"name": "Alice", "other": "Bob"})
        self.assertEqual(result, "{{name}} and Bob")

    def test_shell_var_with_real_placeholder_nearby(self) -> None:
        """${name} stays literal while {other} is substituted."""
        result = substitute("${name} and {other}", {"name": "Alice", "other": "Bob"})
        self.assertEqual(result, "${name} and Bob")

    def test_no_double_substitution(self) -> None:
        """A value that itself contains {x} must not be re-substituted (single pass)."""
        result = substitute("{a}", {"a": "{b}", "b": "surprise"})
        self.assertEqual(result, "{b}")

    def test_json_wrapper_substitution(self) -> None:
        self.assertEqual(
            substitute('{"value": {key}}', {"key": "hello"}),
            '{"value": hello}',
        )

    def test_multiple_keys(self) -> None:
        result = substitute("{a} and {b}", {"a": "foo", "b": "bar"})
        self.assertEqual(result, "foo and bar")

    def test_partial_substitution(self) -> None:
        result = substitute("{a} and {b}", {"a": "foo"})
        self.assertEqual(result, "foo and {b}")
