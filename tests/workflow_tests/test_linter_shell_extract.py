"""Tests for shell-text extraction (workflow.shell_text) and lint-rule serialisation."""

from __future__ import annotations

import unittest
from typing import cast

from tests.workflow_tests.helpers.shell_lint import (
    _BARE_PYTHON,
    _lint,
    _stage,
    _workflow,
)
from workflow.linter_shell import RULE_PYTHON_NOT_ISOLATED
from workflow.linter_types import LintWarning
from workflow.shell_text import (
    extract_shell_segments,
    quote_context,
)


# ---------------------------------------------------------------------------
# Shell-text extraction and serialisation
# ---------------------------------------------------------------------------


class TestExtractShellSegments(unittest.TestCase):
    def _texts(self, description: str) -> list[str]:
        return [s.text for s in extract_shell_segments(description)]

    def test_command_lines_spans_and_fences(self) -> None:
        desc = (
            "Intro prose mentioning gh in the middle.\n"
            "  ./bin/github pr view --pr 1\n"
            "Then run `git status --short` and read `outputs/x.json`.\n"
            "```bash\nmake test\n```\n"
            "```json\n{\"a\": 1}\n```\n"
        )
        texts = self._texts(desc)
        self.assertIn("./bin/github pr view --pr 1", texts)
        self.assertIn("git status --short", texts)
        self.assertIn("make test", texts)
        self.assertNotIn("outputs/x.json", texts)
        self.assertFalse(any('"a"' in t for t in texts), msg="json fence is not shell")

    def test_continuation_and_open_quote_pull_lines_in(self) -> None:
        desc = "  HOST=$(./bin/workflow check-params m.json \\\n    --print ollama_host) || exit 1\n"
        self.assertEqual(len(self._texts(desc)), 1)
        self.assertIn("--print ollama_host", self._texts(desc)[0])

    def test_weak_words_need_shell_context(self) -> None:
        self.assertEqual(self._texts("  make sure the gate runs\n  test coverage matters\n"), [])
        self.assertEqual(self._texts("  make -C src lint\n"), ["make -C src lint"])

    def test_loop_head_needs_do_on_the_line(self) -> None:
        # receipts-domain-build.yaml: Python's `for parser in PARSERS:` was
        # read as shell before this; so was prose quoting `for R in $ROOTS`.
        self.assertEqual(self._texts("  for parser in PARSERS:\n"), [])
        self.assertEqual(self._texts("Note `for R in $ROOTS` splits.\n"), [])
        self.assertEqual(self._texts("  for p in a b; do echo $p; done\n"), ["for p in a b; do echo $p; done"])

    def test_prose_line_closing_a_paren_is_not_shell(self) -> None:
        self.assertEqual(self._texts("  git add -A) and run /open-pr with a title\n"), [])

    def test_fence_marker_alone_on_its_line_is_still_recognized(self) -> None:
        # Happy path: a normal fence, unaffected by folded-scalar collapsing,
        # still yields one fence segment with all its body lines intact.
        desc = "```bash\necho setup\nfor p in items; do echo \"$p\"; done\n```\n"
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')

    def test_folded_scalar_collapses_fence_marker_onto_first_command(self) -> None:
        # PR #433 review: most workflow stages use YAML folded scalars
        # (`description: >`), which collapse a fence's opening marker line
        # and its first command onto one line before this function ever
        # sees them -- "```bash" + "echo setup" arrives as
        # "```bash echo setup". The old _FENCE_RE required the marker alone
        # on its line, so it missed that line entirely and the whole fenced
        # block -- including the loop line -- was silently dropped as shell.
        desc = '```bash echo setup\nfor p in items; do echo "$p"; done\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')
        # The collapsed first command must survive, not be discarded.
        self.assertIn("echo setup", fence_segments[0].text)

    def test_folded_scalar_collapses_unlabelled_fence_marker_onto_first_command(self) -> None:
        # PR #433 review (follow-up): the fix above only covers a LABELLED
        # fence folded onto one line ("```bash echo setup"). An UNLABELLED
        # fence folded the same way ("``` echo setup") has no language tag,
        # but the lang-tag group in _FENCE_OPEN_RE is greedy and captures
        # "echo" as if it were one; _fence_is_shell then rejected it
        # ("echo" not in _SHELL_FENCE_LANGS) and the whole block -- an
        # unlabelled fence whose first line is a command, which the module's
        # own contract says counts as shell -- was silently dropped.
        desc = '``` echo setup\nfor p in items; do echo "$p"; done\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(len(fence_segments), 1)
        self.assertEqual(fence_segments[0].text, 'echo setup\nfor p in items; do echo "$p"; done')

    def test_folded_scalar_collapsed_unlabelled_fence_with_prose_first_line_stays_silent(self) -> None:
        # Sibling near-miss: when the collapsed first line is NOT a command
        # (prose, not a recognised command word), the fence must still be
        # rejected as non-shell -- the fix must not turn every unlabelled
        # collapsed fence into shell regardless of content.
        desc = "``` this is just prose\nmore prose\n```\n"
        self.assertEqual(extract_shell_segments(desc), [])

    def test_folded_python_fence_is_not_reclassified_as_unlabelled_shell(self) -> None:
        # PR #433 review: a REAL language tag ("python") folded onto one
        # line by a YAML folded scalar ("```python python3 -c ...") has the
        # same shape, after folding, as the unlabelled-fence case above --
        # an unrecognised tag with trailing text. Before this fix, both
        # were handled identically: the fallback discarded the tag and
        # treated "python python3 -c ..." as an unlabelled fence's first
        # body line, and "python3" (a strong command in _STRONG_COMMANDS)
        # made the fence lint as shell. A python-labelled fence is not a
        # shell fence and must yield zero fence segments.
        desc = '```python python3 -c "print(1)"\nmore_code = 2\n```\n'
        segments = extract_shell_segments(desc)
        fence_segments = [s for s in segments if s.origin == "fence"]
        self.assertEqual(fence_segments, [])

    def test_folded_unlabelled_fence_opening_with_python_is_shell(self) -> None:
        # PR #433 review (shell_text.py:317): the space after the marker
        # marks "python" as the body's first word, not a language tag.
        desc = "``` python -c 'print(1)'\nmore_code\n```\n"
        fence_segments = [s for s in extract_shell_segments(desc) if s.origin == "fence"]
        self.assertEqual([s.text for s in fence_segments], ["python -c 'print(1)'\nmore_code"])

    def test_spaced_shell_tag_with_trailing_text_stays_shell(self) -> None:
        # "``` bash echo x" is shell whichever way the word is read.
        desc = "``` bash echo x\n```\n"
        self.assertEqual(len([s for s in extract_shell_segments(desc) if s.origin == "fence"]), 1)

    def test_spaced_tag_alone_on_its_line_keeps_its_language(self) -> None:
        # Nothing was folded onto "``` python", so the word is its tag.
        self.assertEqual(extract_shell_segments("``` python\nprint(1)\n```\n"), [])

    def test_folded_unlabelled_fence_opening_with_single_word_command(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Wg: "``` echo" has a gap but no
        # trailing text, so "echo" was returned as the language and the fence
        # was dropped although its first body line is a command.
        self.assertEqual(self._texts("``` echo\nhi\n```\n"), ["echo\nhi"])
        self.assertEqual(self._texts("``` python3\n```\n"), ["python3"])

    def test_python_tagged_fences_stay_non_shell(self) -> None:
        # Happy path: a glued "```python" tag, and the spaced "``` python"
        # language tag, are still Python fences.
        for desc in ("```python\nprint(1)\n```\n", "``` python\nprint(1)\n```\n",
                     "``` python\nimport os\n```\n"):
            with self.subTest(desc=desc):
                self.assertEqual(extract_shell_segments(desc), [])

    def test_bare_interpreter_operand_is_a_command_line(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2U4: a suffixless script operand.
        self.assertEqual(self._texts("  python3 runner\n"), ["python3 runner"])
        self.assertEqual(self._texts("  python3 runner -v\n"), ["python3 runner -v"])

    def test_bare_script_with_further_operands_is_a_command_line(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nGwUo.
        for line in ("python3 runner input", "python3 runner --flag",
                     "python3 tools/gen.py a b", "python3 -m pkg x"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [line])

    def test_interpreter_prose_is_not_a_command_line(self) -> None:
        for line in ("python3 is required", "python3 is required for this step",
                     "python must be 3.11 or newer", "python3 must be installed",
                     "python3 and pip", "Python 3.11 or newer", "python 3.11 or newer",
                     "python3 is."):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_digit_led_script_is_a_command_line(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nH402.
        for line in ("python3 3.py", "python3 2026_job.py", "python3 3x"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [line])

    def test_dotted_version_is_prose(self) -> None:
        for line in ("python3 3.11,", "python3 3", "python 3.11.4 only"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_wrapper_led_lines_are_command_lines(self) -> None:
        # PR #437 "Previously missed" finding: wrappers parse_shell sees
        # through (WRAPPER_NAMES) now lead a command line when what they run
        # is itself a command.
        for line in ("env FOO=1 python3 -c 'print(1)'", "timeout 5 python3 run.py",
                     "timeout 1200 ./bin/github pr checks --pr 1", "nohup git fetch",
                     "time -p make -C src lint", "command rm -f x"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [line])

    def test_prose_led_by_a_wrapper_word_is_not_a_command_line(self) -> None:
        # Happy path: the words that follow a wrapper-shaped English word are
        # prose, so the line is too. The last three are real lines from
        # workflows/code/qwen-local-handler.yaml and qwen-admin.yaml.
        for line in ("env vars must be set before the run", "time to wait for CI",
                     "time regardless of lock state.", "timeout to interrupt a blocked handler",
                     "timeout — so the exposure is seconds rather than minutes,",
                     "nice to have: a faster runner"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_assignment_and_if_lines_are_commands(self) -> None:
        self.assertEqual(self._texts("  export FOO=1\n"), ["export FOO=1"])
        self.assertEqual(self._texts("  if true; then echo ok; fi\n"), ["if true; then echo ok; fi"])
        self.assertEqual(self._texts("  if the gate fails, stop\n"), [])

    def test_quote_context_handles_nested_substitution(self) -> None:
        text = 'X="$(jq -r \'.a\' "$F")" {k}'
        ctx = quote_context(text)
        self.assertEqual(ctx[text.index(".a")], "'")
        self.assertEqual(ctx[text.index("{k}")], "")
        self.assertEqual(ctx[text.index("$F")], '"')

    def test_versioned_interpreter_is_a_command_line(self) -> None:
        # Unlinked triage finding shell_text.py:209: only the exact names
        # "python"/"python3", or a path ending in "/python3", were recognised
        # -- a versioned interpreter like python3.11 was silently treated as
        # prose and extracted no segment at all.
        self.assertEqual(self._texts("  python3.11 tools/run_checks\n"), ["python3.11 tools/run_checks"])
        self.assertEqual(
            self._texts("  /usr/bin/python3.12 -c 'print(1)'\n"),
            ["/usr/bin/python3.12 -c 'print(1)'"],
        )

    def test_unversioned_python_still_a_command_line(self) -> None:
        # Happy-path sibling: the pre-existing exact-name/-path forms this
        # function already handled must keep working after generalising to
        # the regex-based versioned check.
        self.assertEqual(self._texts("  python3 -c 'print(1)'\n"), ["python3 -c 'print(1)'"])
        self.assertEqual(
            self._texts("  /usr/bin/python3 -c 'print(1)'\n"), ["/usr/bin/python3 -c 'print(1)'"],
        )

    def test_heredoc_body_is_included_in_the_line_segment(self) -> None:
        # Unlinked triage finding shell_text.py:305: _line_segments only ever
        # emitted the heredoc OPENER line -- the opener itself has no
        # unclosed quote or trailing backslash, so _can_continue stopped
        # right after it and the body never became part of any segment's
        # text. A caller-supplied placeholder substituted into an unquoted
        # (shell-expanding) heredoc body must reach the same segment text a
        # {param} scan inspects.
        desc = "cat <<EOF\n{host}\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1)
        self.assertIn("{host}", segments[0].text)
        self.assertEqual(segments[0].text, "cat <<EOF\n{host}\nEOF")

    def test_quoted_heredoc_body_is_absorbed(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nOAmF: a {param} is substituted
        # before bash parses the heredoc, so the pre-shell rule needs a quoted
        # body's text too. The parser still marks it inert for the
        # shell-expansion rules (see TestUnboundVariable's quoted-heredoc tests).
        desc = "cat <<'EOF'\n{host}\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "cat <<'EOF'\n{host}\nEOF")

    def test_quoted_heredoc_body_is_not_its_own_segment(self) -> None:
        # PR #433 review: a command-looking body line must not be revisited
        # as an INDEPENDENT live segment. One segment in total, the opener
        # with its body.
        desc = "cat <<'EOF'\necho \"$UNBOUND\"\nEOF\n"
        segments = extract_shell_segments(desc)
        self.assertEqual(len(segments), 1, msg=segments)
        self.assertEqual(segments[0].text, "cat <<'EOF'\necho \"$UNBOUND\"\nEOF")

    def test_control_operator_after_interpreter_prose_word_is_shell(self) -> None:
        # Copilot "Previously missed" on shell_text.py:286: the interpreter
        # prose exception judged only `is`, so the rm after the operator was
        # never extracted and every rule missed it.
        for line in ("python3 is; rm -rf scratch", "python3 is && rm -rf scratch",
                     "python3 is || rm -rf scratch", "python3 is | grep x",
                     "python3 is $(rm -rf scratch)", "python3 is > /dev/null"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [line])

    def test_control_operator_after_wrapper_that_runs_nothing_is_shell(self) -> None:
        # Same finding, wrapper-led: `env` alone resolves no command, so the
        # pipe into grep was dropped with it.
        self.assertEqual(self._texts("  env | grep OTEL_\n"), ["env | grep OTEL_"])
        self.assertEqual(self._texts("  timeout to x; rm -rf y\n"), ["timeout to x; rm -rf y"])

    def test_prose_with_operator_characters_stays_prose(self) -> None:
        # Happy path: English interpreter lines, including ones whose
        # punctuation lexes as an operator not followed by a command, and
        # operators inside quotes or a comment.
        for line in ("python3 is required", "Note: python3 is fast", "python3 is fast; use it",
                     "python3 script for the aggregation; it is deterministic.",
                     "python 3.11 or newer (>= 3.11)", 'python3 is "x; rm y"',
                     "python3 is # a; rm x", "timeout to interrupt a handler; read job_runtime before"):
            with self.subTest(line=line):
                self.assertEqual(self._texts(f"  {line}\n"), [])

    def test_long_run_of_joined_prose_does_not_exhaust_the_stack(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV676: each prose command before a
        # joining operator recursed into is_command_line, so ~1,000 of them
        # raised RecursionError out of the lint. Nested substitutions did too.
        for line in ("python3 is; " * 1000 + "rm -rf scratch", "python3 is $(" * 1000 + "x"):
            with self.subTest(line=line[:24]):
                self.assertEqual(self._texts(f"  {line}\n"), [line])
                self.assertTrue(_lint(_workflow(_stage(f"Run:\n\n  {line}\n"))).valid)

    def test_joined_prose_within_the_bound_is_judged_as_before(self) -> None:
        # Happy path: a few joins are still judged text by text; only a line
        # needing more than the bound is called shell without judging the rest.
        self.assertEqual(self._texts("  python3 is; python3 is fast; it is fine\n"), [])
        self.assertEqual(self._texts("  python3 is; python3 is fast; rm -rf x\n"),
                         ["python3 is; python3 is fast; rm -rf x"])
        many = "python3 is; " * 100 + "it is fine"
        self.assertEqual(self._texts(f"  {many}\n"), [many])



class TestRuleSerialisation(unittest.TestCase):
    def test_rule_id_is_serialised(self) -> None:
        result = _lint(_workflow(_stage(_BARE_PYTHON)))
        warnings = cast(list[dict[str, str]], result.as_dict()["warnings"])
        self.assertEqual([w["rule"] for w in warnings], [RULE_PYTHON_NOT_ISOLATED])

    def test_unnamed_warning_serialises_empty_rule(self) -> None:
        w = LintWarning(stage="s", field="f", message="m")
        self.assertEqual(w.rule, "")


if __name__ == "__main__":
    unittest.main()
