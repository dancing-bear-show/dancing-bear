"""Tests for the python-not-isolated lint rule (workflow.linter_shell)."""

from __future__ import annotations

import unittest

from tests.workflow_tests.helpers.shell_lint import (
    BARE_PYTHON,
    _RuleCase,
    _stage,
    _workflow,
)
from workflow.linter_shell import RULE_PYTHON_NOT_ISOLATED


# ---------------------------------------------------------------------------
# python-not-isolated
# ---------------------------------------------------------------------------



class TestPythonNotIsolated(_RuleCase):
    rule = RULE_PYTHON_NOT_ISOLATED

    def test_fires_on_historical_bare_interpreter(self) -> None:
        hits = self.assert_fires(_workflow(_stage(BARE_PYTHON)))
        self.assertIn("lacks -I", hits[0].message)

    def test_fires_on_script_and_venv_interpreter(self) -> None:
        for command in ("python3 workflows/code/scripts/detect_facades.py --root src",
                        ".venv/bin/python tests/fixtures/build.py",
                        "python3 -S -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_isolated_forms_are_silent(self) -> None:
        for command in ("python3 -I -S -c 'print(1)'", "python3 -IS -c 'print(1)'",
                        "python3 -I -m json.tool f.json", ".venv/bin/python -I -m pip install x",
                        "python3 -E -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_explicit_pythonpath_is_exempt(self) -> None:
        desc = 'Run:\n\n  PYTHONPATH="$PWD/src" python3 -m unittest tests.workflow_tests -v\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_prose_is_silent(self) -> None:
        self.assert_silent(_workflow(_stage("Run:\n\n  python3 is required for this step\n")))

    def test_fires_on_non_py_suffixed_script_operand(self) -> None:
        # Copilot PR #433 r4099834636: a script path with no .py suffix, or a
        # quoted variable holding the script path, still starts the
        # interpreter with the ambient PYTHONPATH.
        for command in ('python3 tools/run_checks', 'python3 "$SCRIPT"'):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_pythonpath_assignment_in_a_prior_command_does_not_exempt(self) -> None:
        # PR #433 review r4118063072 (and unlinked triage finding
        # linter_shell.py:489, same root cause): the exemption scanned the
        # previous 3 tokens for any PYTHONPATH= prefix with no regard for
        # command boundaries, so an assignment belonging to a PRIOR, unrelated
        # command -- separated here by ';' -- wrongly exempted the python
        # invocation that follows it. The interpreter still inherits the
        # ambient PYTHONPATH and is not isolated.
        desc = 'Run:\n\n  echo PYTHONPATH=/tmp; python3 tools/run_checks\n'
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("lacks -I", hits[0].message)

    def test_pythonpath_assignment_in_the_same_command_still_exempts(self) -> None:
        # Happy-path sibling: a real same-command PYTHONPATH= prefix -- no
        # separator between it and the python invocation -- must keep
        # exempting the call, same as test_explicit_pythonpath_is_exempt.
        desc = 'Run:\n\n  echo setup; PYTHONPATH="$PWD/src" python3 tools/run_checks\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_versioned_interpreter(self) -> None:
        # Unlinked triage finding shell_text.py:209: _is_command_word only
        # recognised the exact names "python"/"python3" or a path ending in
        # "/python3", so a versioned interpreter line was never extracted as
        # shell at all -- this rule never even saw it to flag it.
        for command in ("python3.11 tools/run_checks", "/usr/bin/python3.12 -c 'print(1)'"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_isolated_versioned_interpreter_is_silent(self) -> None:
        # Happy-path sibling: a versioned interpreter that IS isolated must
        # not fire, same as the unversioned forms in test_isolated_forms_are_silent.
        self.assert_silent(_workflow(_stage("Run:\n\n  python3.11 -I -S -c 'print(1)'\n")))

    def test_fires_on_bare_interpreter_with_no_operands(self) -> None:
        # PR #433 review r4118063056: _is_invocation([]) returned False, so a
        # command line consisting of just "python3"/"python" -- with no
        # operands at all -- was never reported as unisolated, even though
        # extract_shell_segments has already decided this is a real command
        # line (not prose) and it still starts the interpreter with the
        # ambient PYTHONPATH.
        for command in ("python3", "python"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("lacks -I", hits[0].message)

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(BARE_PYTHON)))

    def test_isolated_form_after_value_taking_flag_is_silent(self) -> None:
        # Copilot PRRT_kwDOQr1kjM6mhoot (PR #433): the flag scan stopped at
        # the first arg not starting with "-", so "-X utf8" (a value-taking
        # flag whose value is the NEXT token) was misread as the end of the
        # flag list and "-I" right after it was never reached.
        for command in (
            "python3 -X utf8 -I -c 'print(1)'",
            "python3 -W error -I -c 'print(1)'",
            "python3 -X utf8 -W error -I -c 'print(1)'",
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_interpreter_as_an_argument_is_silent(self) -> None:
        # PR #433 review (linter_shell.py:570): every token matching the
        # interpreter name was treated as an invocation, so `echo python3 -c`
        # warned although echo runs, not python3.
        for command in ("echo python3 -c 'print(1)'", "test -x .venv/bin/python",
                        "grep -n python3 setup.cfg"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_interpreter_in_command_position_after_a_separator_fires(self) -> None:
        # Happy path for the same fix: the interpreter is still found wherever
        # it IS the program -- after a separator, a reserved word, a wrapper,
        # or inside a command substitution.
        for command in ("echo setup; python3 -c 'print(1)'",
                        "if python3 -c 'import x'; then echo ok; fi",
                        "cd src && env FOO=1 python3 -c 'print(1)'",
                        "X=$(python3 -c 'print(1)'); echo \"$X\""):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_bare_interpreter_before_a_separator_fires(self) -> None:
        # PR #433 review (linter_shell.py:574): the operand list ran past
        # the separator, so `;`/`&&` became the first operand and the bare
        # interpreter was taken for prose.
        for command in ("python3 ; echo done", "python3 && echo done"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("lacks -I", hits[0].message)

    def test_isolated_interpreter_before_a_separator_is_silent(self) -> None:
        # Happy path: bounding the operands must not drop a later command's
        # flags onto the interpreter or lose its own.
        for command in ("python3 -I ; echo done", "python3 -I -c 'print(1)' && echo -X"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_env_pythonpath_exempts_only_its_own_command(self) -> None:
        self.assert_silent(_workflow(_stage("Run:\n\n  cd src && env PYTHONPATH=. python3 -m foo\n")))
        self.assert_fires(_workflow(_stage("Run:\n\n  cd src && env PYTHONPATH=. true; python3 -m foo\n")))

    def test_fires_in_folded_unlabelled_fence_opening_with_python(self) -> None:
        # PR #433 review (shell_text.py:317): "``` python -c ..." -- an
        # unlabelled fence folded onto its first command -- was read as a
        # fence tagged `python` and dropped, so the unisolated call was never
        # linted. The space after the marker marks the word as body text.
        hits = self.assert_fires(_workflow(_stage("``` python -c 'print(1)'\n```\n")))
        self.assertIn("lacks -I", hits[0].message)

    def test_folded_python_tagged_fence_is_still_not_shell(self) -> None:
        # Happy path: a glued tag ("```python") is a language tag; the
        # fence is Python source, not shell.
        self.assert_silent(_workflow(_stage("```python python3 -c 'print(1)'\n```\n")))

    def test_value_taking_flag_without_isolation_flag_still_fires(self) -> None:
        # Sad-path sibling: consuming -X's value must not itself grant
        # isolation -- a command with -X but no -I/-E still lacks it.
        hits = self.assert_fires(_workflow(_stage("Run:\n\n  python3 -X utf8 -c 'print(1)'\n")))
        self.assertIn("lacks -I", hits[0].message)

    def test_fires_on_bare_relative_script_operand(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2U4: `_is_invocation(["runner"])`
        # was False, so `python3 runner` -- a script with no suffix and no
        # slash -- started the interpreter with the ambient PYTHONPATH
        # unreported. Prose is now kept out by the segment extractor instead.
        for command in ("python3 runner", "python3 runner --verbose"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("python3 runner", hits[0].message)

    def test_fires_on_bare_script_with_further_operands(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nGwUo: the word-count heuristic read
        # `python3 runner input` as prose, so it was never linted. Only the
        # word after the interpreter decides now.
        for command in ("python3 runner input", "python3 runner --flag",
                        "python3 tools/gen.py a b", "python3 -m pkg x"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn(command, hits[0].message)

    def test_interpreter_prose_sentences_are_silent(self) -> None:
        # Happy path for the same thread: English after the interpreter word.
        for line in ("python3 is required", "python3 must be installed", "python3 and pip",
                     "Python 3.11 or newer", "python 3.11 or newer",
                     "python3 script for the aggregation; it is deterministic."):
            with self.subTest(line=line):
                self.assert_silent(_workflow(_stage(f"Setup:\n\n  {line}\n")))

    def test_fires_on_digit_led_script_name(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nH402: any operand starting with a
        # digit read as a version, so these scripts were never linted.
        for command in ("python3 3.py", "python3 2026_job.py", "python3 3x"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn(command, hits[0].message)

    def test_dotted_version_prose_is_silent(self) -> None:
        # Happy path for the same thread: an all-numeric dotted version.
        for line in ("python 3.11 or newer", "python3 3.11,", "python3 3", "python 3.11.4 only"):
            with self.subTest(line=line):
                self.assert_silent(_workflow(_stage(f"Setup:\n\n  {line}\n")))

    def test_fires_on_interpreter_prose_word_before_control_operator(self) -> None:
        # Copilot "Previously missed" on shell_text.py:286: the line is now
        # shell, so its unisolated interpreter is reported.
        for line in ("python3 is; rm -rf scratch", "python3 is && rm -rf scratch"):
            with self.subTest(line=line):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {line}\n")))

    def test_python_is_required_prose_is_silent(self) -> None:
        # Happy path for the same thread: with the operand heuristic gone,
        # "python3 is required" stays silent because it is never a segment.
        self.assert_silent(_workflow(_stage("Setup:\n\n  python3 is required\n")))

    def test_fires_on_wrapper_led_interpreter_line(self) -> None:
        # PR #437 "Previously missed" (shell_text.py is_command_line): a line
        # led by a wrapper parse_shell sees through produced no segment, so
        # its unisolated interpreter was never linted.
        for command in ("env FOO=1 python3 -c 'print(1)'", "timeout 5 python3 run.py",
                        "sudo -u me nice -n 5 python3 run.py"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_fires_on_path_qualified_wrapper_led_interpreter_line(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV67o: extraction compared the raw
        # first word with the wrapper names, so `/usr/bin/env python3 runner`
        # produced no segment although parse_shell resolves the basename.
        for command in ("/usr/bin/env python3 runner", "/usr/bin/timeout 5 python3 run.py"):
            with self.subTest(command=command):
                self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_path_qualified_wrapper_prose_is_silent(self) -> None:
        # Happy path: the wrapper still counts only when what it runs is a command.
        self.assert_silent(_workflow(_stage("Setup:\n\n  /usr/bin/env is how python3 is found\n")))

    def test_fires_in_folded_unlabelled_fence_opening_with_single_word(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Wg: "``` python3" -- an unlabelled
        # fence whose first line is the bare interpreter -- was read as a fence
        # tagged `python3` and dropped.
        self.assert_fires(_workflow(_stage("Run:\n\n  ``` python3\n  ```\n")))


if __name__ == "__main__":
    unittest.main()
