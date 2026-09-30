"""Tests for the shell-guard-refused lint rule (workflow.linter_shell, workflow.shell_guard)."""

from __future__ import annotations

import unittest

from tests.workflow_tests.helpers.shell_lint import (
    _OLLAMA_PARAMS,
    _OLLAMA_RULE,
    _RuleCase,
    _stage,
    _workflow,
)
from workflow.linter_shell import RULE_GUARD_REFUSED


# ---------------------------------------------------------------------------
# shell-guard-refused
# ---------------------------------------------------------------------------

# qwen-admin.yaml health stage at f00a50d5 (PR #391 round 7), adapted to an
# UNQUOTED delimiter: the guard's own contract (guard-contract.yaml "heredoc
# subst runs" -> block) only refuses this shape because $(...) in the body
# expands before the guard can inspect the result. The original fixture used
# a quoted `<<'RAW'` delimiter, which the guard allows outright ("quoted
# heredoc data" -> allow) -- Copilot PR #433 flagged that mismatch directly.
_HEREDOC = """
    Get the value off the command line:

      cat > "$TMPDIR/qwen-admin-host" <<RAW
      $(echo {ollama_host})
      RAW
"""
# review-fix-threads.yaml verify-fixes, adapted to a mutating body: the guard
# allows a read-only loop outright (guard-contract.yaml "loop variable in a
# read" -> allow), so the original `do make test; done` body -- a false
# positive Copilot PR #433 flagged -- must not fire this rule any more.
_LOOP = "Run twice:\n\n  for pass in 1 2; do rm -rf \"$TMPDIR/scratch-$pass\"; done\n"


def _nested_subs(levels: int) -> str:
    """A read-only command inside *levels* nested ``$(...)`` substitutions."""
    text = "wc -l x"
    for _ in range(levels):
        text = f"echo $({text})"
    return text


def _nested_sh_c(inner: str, levels: int) -> str:
    """*inner* run through *levels* nested path-qualified ``/bin/sh -c`` strings.

    Double-quote escaping doubles the backslashes at every level, so a pure
    33-level ``sh -c`` chain is gigabytes long; the depth tests combine a few
    ``sh -c`` levels with substitutions, which the guard counts the same way.
    """
    text = inner
    for _ in range(levels):
        escaped = "".join("\\" + ch if ch in '\\"$`' else ch for ch in text)
        text = f'/bin/sh -c "{escaped}"'
    return text


class TestGuardRefused(_RuleCase):
    rule = RULE_GUARD_REFUSED

    def test_fires_on_historical_heredoc(self) -> None:
        hits = self.assert_fires(_workflow(_stage(_HEREDOC), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))
        self.assertIn("heredoc", hits[0].message)

    def test_fires_on_shell_loops(self) -> None:
        for desc in (_LOOP, "Drain:\n\n  while test -s q.txt; do mv q.txt \"$TMPDIR/done\"; done\n"):
            with self.subTest(desc=desc):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_quoted_mutating_command_name_as_argument_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:631: _loop_body_is_mutating
        # treated ANY token equal to a mutating command name as an executed
        # command regardless of shell command position. shlex strips quotes
        # during tokenisation, so a quoted argument like "rm" passed to echo
        # is indistinguishable at the token level from a bare rm invocation --
        # but it is not one: echo just prints the word "rm", the loop reads
        # only.
        desc = 'Report:\n\n  for f in src/*.py; do echo "rm" "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_mutating_command_after_argument_use_still_fires(self) -> None:
        # Sad-path sibling: a genuine mutating invocation in COMMAND position
        # later in the same loop body must still fire, so the command-position
        # check does not accidentally suppress every mention of the word.
        desc = 'Report:\n\n  for f in src/*.py; do echo "rm"; rm -f "$f"; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fires_on_path_qualified_mutating_command(self) -> None:
        # PR #433 review (linter_shell.py:844): mutators were matched by exact
        # bare token, while the guard resolves the basename -- `/bin/rm` in a
        # loop was refused by the guard and passed here.
        for command in ('for p in files; do /bin/rm -f "$p"; done',
                        'for p in files; do "$HOME/bin/../../bin/mv" "$p" x; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_path_qualified_read_only_command_is_silent(self) -> None:
        # Happy path: basename matching must not turn a read into a write.
        self.assert_silent(_workflow(_stage('Run:\n\n  for p in files; do /usr/bin/wc -l "$p"; done\n')))

    def test_fires_on_mutating_command_after_wrapper_or_reserved_word(self) -> None:
        # PR #433 review (linter_shell.py:844, second finding): a command was
        # in command position only as the first token or after punctuation,
        # so `env rm` and `then rm` were skipped although the guard refuses
        # both. Wrappers and reserved words now pass command position on.
        for command in (
            'for f in files; do env rm -f "$f"; done',
            'for f in files; do if true; then rm -f "$f"; fi; done',
            'for f in files; do sudo -u me rm "$f"; done',
            'for f in files; do timeout 5 nice -n 2 rm "$f"; done',
            'for f in files; do echo "$f" | xargs -n 1 rm; done',
            'for f in files; do FOO=1 command rm "$f"; done',
            'for f in files; do ! rm "$f"; done',
        ):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_mutating_name_as_wrapper_or_keyword_argument_is_silent(self) -> None:
        # Happy path: after a wrapper or keyword, only the command word counts.
        for command in (
            'for f in files; do env FOO=1 wc -l "$f"; done',
            "for f in files; do command -v rm; done",
            'for f in files; do if true; then echo rm "$f"; fi; done',
            'for f in files; do timeout 5 grep rm "$f"; done',
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_command_after_the_loop_ends_is_not_in_the_loop(self) -> None:
        # The old body scan ran to the end of the segment, past `done`.
        self.assert_silent(_workflow(_stage('Run:\n\n  for f in a; do cat "$f"; done; rm -f x\n')))

    def test_redirect_on_the_loop_itself_fires(self) -> None:
        # `done > file` redirects the whole loop's output.
        desc = 'Run:\n\n  for f in a; do cat "$f"; done > out.txt\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_here_string_and_prose_are_silent(self) -> None:
        for desc in (
            "Run:\n\n  jq -r . <<< '{}'\n",
            "NEITHER IS A HEREDOC. The earlier `<<'RAW'` form was broken.\n",
            "The loop reads a file: zsh does not word-split `for R in $ROOTS`.\n",
            'Run:\n\n  echo "use <<EOF in a script, not here"\n',
        ):
            with self.subTest(desc=desc):
                self.assert_silent(_workflow(_stage(desc)))

    def test_quoted_heredoc_delimiter_is_silent(self) -> None:
        # Copilot PR #433 review: a quoted delimiter makes the body inert data --
        # no expansion occurs inside it at all -- so the guard allows it outright
        # (guard-contract.yaml "quoted heredoc data" -> allow). This must not fire
        # even though {ollama_host} sits in the body, unlike the unquoted _HEREDOC
        # fixture above.
        desc = (
            "Get the value off the command line:\n\n"
            '  cat > "$TMPDIR/qwen-admin-host" <<\'RAW\'\n'
            "  {ollama_host}\n"
            "  RAW\n"
        )
        self.assert_silent(_workflow(_stage(desc), params=_OLLAMA_PARAMS, rules=_OLLAMA_RULE))

    def test_read_only_loop_is_silent(self) -> None:
        # guard-contract.yaml "loop variable in a read" -> allow: a loop whose
        # body only reads is not something the guard refuses, so this rule must
        # not warn on it either.
        desc = 'Report line counts:\n\n  for f in src/*.py; do wc -l "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_static_heredoc_body_is_silent(self) -> None:
        # PR #433 review: _has_heredoc previously fired for every unquoted
        # delimiter regardless of body content. The guard only fails to
        # inspect a heredoc body that contains a substitution -- a purely
        # literal body like this one is something the guard accepts outright.
        desc = (
            "Write the file:\n\n"
            '  cat > "$TMPDIR/notes.txt" <<EOF\n'
            "  literal\n"
            "  EOF\n"
        )
        self.assert_silent(_workflow(_stage(desc)))

    def test_unquoted_heredoc_with_backtick_substitution_fires(self) -> None:
        # A backtick substitution in the body is just as unresolvable to the
        # guard as $(...); the sad path for the static-body fix must still
        # catch this shape.
        desc = (
            "Write the file:\n\n"
            '  cat > "$TMPDIR/notes.txt" <<EOF\n'
            "  `date`\n"
            "  EOF\n"
        )
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("heredoc", hits[0].message)

    def test_python_for_loop_is_not_shell(self) -> None:
        desc = "Inline:\n\n  python3 -I -S -c \"\n  for parser in PARSERS:\n      print(parser)\n  \"\n"
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_loop_preceded_by_setup_line_in_same_fence(self) -> None:
        # Copilot PR #433 r4099834657: split_tokens discards newlines, so a
        # loop head right after setup text in the same fenced block glued
        # onto that text's last word instead of following a separator. The
        # blank line here is only to survive the folded (`>`) YAML scalar
        # this fixture format uses -- extract_shell_segments still returns
        # the setup line and the loop as a single fence segment either way.
        # The body removes a file (mutating), so this also stays a positive
        # case under the guard-contract-aligned loop check.
        desc = "```bash\necho setup\n\nfor p in items; do rm -f \"$p\"; done\n```\n"
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("loop", hits[0].message)

    def test_fires_on_loop_with_sed_in_place(self) -> None:
        # PR #433 review r4099834XXX: sed -i is a write per the guard's
        # "Written" table but was absent from _MUTATING_COMMANDS, so a loop
        # calling it passed shell-guard-refused even though the guard refuses it.
        for command in (
            'for p in files; do sed -i "s/a/b/" "$p"; done',
            'for p in files; do sed --in-place "s/a/b/" "$p"; done',
            'for p in files; do sed -ie "s/a/b/" "$p"; done',
        ):
            with self.subTest(command=command):
                desc = f"Run:\n\n  {command}\n"
                self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_sed_without_in_place_in_loop_is_silent(self) -> None:
        # sed -n (or any sed call without -i/--in-place) only reads: the
        # guard's "Written" table blocks sed operands only with -i present.
        desc = 'Read:\n\n  for p in files; do sed -n "1p" "$p"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_later_commands_dash_i_flag_does_not_taint_earlier_sed(self) -> None:
        # Unlinked triage findings linter_shell.py:586/601: _has_sed_in_place
        # scanned every token after "sed" in the WHOLE loop body, not just
        # tokens belonging to that invocation, so a LATER unrelated command's
        # own -i-shaped flag (here, "grep -i" after the read-only sed) was
        # wrongly attributed to the earlier sed call, firing a false
        # shell-guard-refused on an otherwise safe read-only loop.
        desc = 'Read:\n\n  for p in files; do sed -n "1p" "$p"; grep -i pattern "$p"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_loop_with_unsafe_patch(self) -> None:
        # patch is refused by the guard unless --dry-run or -o FILE is given,
        # because it writes the files named inside the diff.
        desc = 'Run:\n\n  for p in diffs; do patch < "$p"; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_patch_with_safe_flag_in_loop_is_silent(self) -> None:
        for command in (
            'for p in diffs; do patch --dry-run < "$p"; done',
            'for p in diffs; do patch -o "$p.out" < "$p"; done',
        ):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_later_commands_safe_flag_does_not_exempt_earlier_unsafe_patch(self) -> None:
        # Sad-path sibling for the same bounding fix, applied to patch: a
        # LATER command's --dry-run-shaped token must not be misread as
        # belonging to an earlier, unsafe patch invocation and wrongly
        # exempt it.
        desc = 'Run:\n\n  for p in diffs; do patch < "$p"; echo --dry-run; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fd_duplication_in_loop_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:125/633: _REDIRECT_RE matched
        # file-descriptor duplication like `2>&1`, which the guard treats as
        # non-writing (guard-contract.yaml "fd duplication is not a path" and
        # "fd dup is not a path" -> allow), causing a false shell-guard-refused
        # on an otherwise read-only loop.
        desc = 'Report line counts:\n\n  for f in src/*.py; do wc -l "$f" 2>&1; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_bracket_string_comparison_in_loop_is_silent(self) -> None:
        # Unlinked triage finding linter_shell.py:633: the redirect scanner
        # flagged '>' anywhere in a loop body, including inside a
        # `[[ "$f" > a ]]` shell string comparison, which the guard contract
        # explicitly allows as read-only (guard-contract.yaml
        # "[[ > ]] compares" -> allow).
        desc = 'Compare names:\n\n  for f in src/*.py; do [[ "$f" > "a" ]] && echo "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_redirect_after_bracket_comparison_still_fires(self) -> None:
        # Sad-path sibling: a genuine write redirect elsewhere in the same
        # loop body must still fire even when a bracket comparison's bare '>'
        # also appears in the body -- the bracket exemption must not swallow
        # an unrelated real redirect.
        desc = (
            "Run:\n\n"
            '  for f in src/*.py; do [[ "$f" > "a" ]] && echo "$f" > out.log; done\n'
        )
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_quoted_redirect_char_as_argument_is_silent(self) -> None:
        # Copilot PRRT_kwDOQr1kjM6mhoo2 (PR #433): split_tokens strips quotes
        # via shlex, so a quoted ">" argument becomes an indistinguishable
        # bare ">" token and was misread as a write redirect. The loop only
        # echoes the character; it writes nothing.
        desc = 'Report:\n\n  for f in files; do echo ">" "$f"; done\n'
        self.assert_silent(_workflow(_stage(desc)))

    def test_real_redirect_alongside_quoted_char_still_fires(self) -> None:
        # Sad-path sibling: a genuine write redirect in the same body as a
        # quoted ">" argument must still fire -- the quote-awareness fix must
        # not blind the scan to a real redirect appearing elsewhere.
        desc = 'Report:\n\n  for f in files; do echo ">" "$f" > out.log; done\n'
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_second_heredoc_with_identical_opener_text_still_inspected(self) -> None:
        # Unlinked triage findings linter_shell.py:552/568: _has_heredoc's
        # full_text.find(text) fallback anchors to the FIRST occurrence of
        # matching opener text, so when two heredocs share an identical
        # opener (same redirect target and delimiter) the second, dangerous
        # one's own substitution-bearing body could be missed if the search
        # ever resolved against the wrong occurrence. Fixed by anchoring the
        # search with the segment's own source offset (ShellSegment.start)
        # rather than a text search. Here the first heredoc's body is static
        # (guard accepts it) and the second, textually-identical-opener
        # heredoc's body substitutes (guard refuses it) -- the rule must
        # still fire, driven by the second occurrence.
        desc = (
            "First write:\n\n"
            '  cat > "out" <<EOF\n'
            "  literal\n"
            "  EOF\n\n"
            "Second write:\n\n"
            '  cat > "out" <<EOF\n'
            "  $(date)\n"
            "  EOF\n"
        )
        hits = self.assert_fires(_workflow(_stage(desc)))
        self.assertIn("heredoc", hits[0].message)

    def test_fires_on_find_write_actions_in_loop(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6ms2Vv: the guard's h_find treats
        # -delete and -fprint as writes, but `cmd.name` was only `find`.
        for command in ('for p in files; do find "$p" -delete; done',
                        'for p in files; do find "$p" -name x -fprint out.txt; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_fires_on_find_exec_mutator_in_loop(self) -> None:
        # Same thread: h_find judges the command after -exec/-execdir/-ok.
        for command in ('for p in files; do find "$p" -exec rm {} +; done',
                        'for p in files; do find "$p" -execdir env mv {} x \\; ; done',
                        'for p in files; do find "$p" -ok sed -i "s/a/b/" {} \\; ; done'):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_read_only_find_in_loop_is_silent(self) -> None:
        # Happy path: find's read-only forms, and a -delete-shaped word that
        # belongs to an -exec body rather than to find, stay silent.
        for command in ("for p in files; do find . -name x; done",
                        "for p in files; do find . -exec grep -n x {} +; done",
                        "for p in files; do find . -exec grep -delete x {} +; done"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_fires_on_eval_and_bare_nested_shell_anywhere(self) -> None:
        # Same thread: block-destructive-bash.sh refuses eval, a bare
        # `sh -c`, and xargs into a shell outright -- in a loop or not.
        for command in ('eval "$CMD"', "bash -c 'echo hi'", "sh -ec 'echo hi'",
                        "echo a | xargs -n 1 sh run.sh", "find . -exec bash -c 'echo {}' \\;"):
            with self.subTest(command=command):
                desc = f"Run:\n\n  ```bash\n  {command}\n  ```\n"
                self.assertIn("eval/sh -c", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_fires_on_mutator_inside_qualified_shell_string_in_loop(self) -> None:
        # Same thread: a /bin/sh -c string escapes the destructive guard's
        # nested-shell check, but _bash_write_targets.py h_shell parses the
        # string and judges its commands; so does this rule. A shell reading
        # its program from stdin is refused by h_shell too.
        for command in ("for f in a; do /bin/sh -c 'rm -f x'; done",
                        "for f in a; do /bin/bash -c 'cd x && touch y'; done",
                        "for f in a; do echo x | /bin/bash; done"):
            with self.subTest(command=command):
                self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_fires_on_stdin_shell_with_clustered_s(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nGwTd: only a standalone `-s` was
        # read, so `bash -es name` -- stdin program, `name` its $0 -- passed
        # while h_shell refuses it. Options are read as clusters now,
        # mirroring the guard's getopt: `-o` takes a value, `+o NAME` and
        # `--rcfile FILE` are skipped, and the first operand ends options.
        for command in ('for p in files; do /bin/bash -es name < "$p"; done',
                        'for p in files; do bash -se name < "$p"; done',
                        'for p in files; do bash -eo pipefail -s name < "$p"; done',
                        'for p in files; do bash +o posix -s name < "$p"; done',
                        'for p in files; do bash --rcfile rc -s < "$p"; done'):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))
                self.assertIn("loop", hits[0].message)

    def test_fires_on_stdin_shell_outside_a_loop(self) -> None:
        # Copilot "Previously missed" on linter_shell.py:927: h_shell
        # (_bash_write_targets.py) refuses a shell reading its program from
        # stdin unconditionally, not only inside a loop.
        for command in ("bash -s name", "/bin/bash < script", "echo x | sh", "bash -es name < f",
                        "zsh"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("shell reading its program from stdin", hits[0].message)

    def test_shell_running_a_script_file_outside_a_loop_is_silent(self) -> None:
        # Happy path: a script operand is a file (command semantics); fish is
        # not a shell h_shell handles, so the guard never refuses it.
        for command in ("bash script.sh", "/bin/bash -e script.sh", "sh -- run.sh", "fish < f"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_shell_running_a_script_file_in_loop_is_silent(self) -> None:
        # Happy path: a script operand with no -s runs a file (command
        # semantics). A `-s` after the script, after `--`, or as `-o`'s value
        # is not the -s option; with -c present the string is judged instead.
        for command in ("for p in files; do /bin/bash -e script.sh; done",
                        "for p in files; do /bin/bash script.sh -s; done",
                        "for p in files; do /bin/bash -- -s; done",
                        "for p in files; do /bin/bash -os script.sh; done",
                        "for p in files; do /bin/bash -cs 'wc -l x' name; done"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  {command}\n")))

    def test_nested_shell_check_follows_the_destructive_guard_regex(self) -> None:
        # block-destructive-bash.sh blocks a bare shell only when letter-only
        # clusters lead to one ending in `c`; `-oc` matches that regex even
        # though getopt reads `c` as -o's value.
        for command in ("bash -oc 'echo hi'", "sh -e -c 'echo hi'"):
            with self.subTest(command=command):
                desc = f"Run:\n\n  ```bash\n  {command}\n  ```\n"
                self.assertIn("eval/sh -c", self.assert_fires(_workflow(_stage(desc)))[0].message)
        for command in ("bash -o pipefail -c 'echo hi'", "bash --norc -c 'echo hi'"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_fires_on_nesting_deeper_than_the_guard_parses(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nH40K: expansion stopped at depth 32
        # and dropped the rest, while _bash_write_targets.py raises ParseError
        # ("nested too deeply") for the whole command -- loop or not. Every
        # sh -c string and every substitution is one level; 33 is refused.
        # Boundaries checked against analyse_command on the same strings.
        for command in (_nested_subs(33), _nested_sh_c(_nested_subs(32), 1),
                        _nested_sh_c(_nested_subs(31), 2), _nested_sh_c(_nested_subs(30), 3),
                        "for f in a; do " + _nested_sh_c(_nested_subs(31), 2) + "; done"):
            with self.subTest(command=command[:40]):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("nesting deeper than 32", hits[0].message)

    def test_nesting_within_the_guard_limit_is_silent(self) -> None:
        # Happy path: depth 32 exactly, and ordinary 2-3 level sh -c nesting.
        for command in (_nested_subs(32), _nested_sh_c(_nested_subs(30), 2),
                        _nested_sh_c("wc -l x", 2), _nested_sh_c("wc -l x", 3),
                        "for f in a; do " + _nested_sh_c("wc -l x", 3) + "; done"):
            with self.subTest(command=command[:40]):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_fires_on_mutator_substituted_inside_an_expansion(self) -> None:
        # Unlinked finding shell_parse.py:364: ${...} and $((...)) bodies were
        # skipped whole, so a $(...) or backtick inside one never reached the
        # parser. Bash runs it, and _bash_write_targets.py (_scan_param,
        # _scan_arith) parses it.
        for command in ('for f in x; do echo "${X:-$(rm -f "$f")}"; done',
                        "for f in x; do echo $(( $(rm -f x) )); done",
                        "for f in x; do (( $(rm -f x) )); done",
                        "for f in x; do echo ${X:-`rm -f x`}; done",
                        "for f in x; do echo ${A:-${B:-$(rm -f x)}}; done"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("loop", hits[0].message)

    def test_expansion_without_a_substitution_is_silent(self) -> None:
        for command in ('for f in x; do echo "${X:-default}"; done',
                        "for f in x; do echo $(( 1 + 2 )); done",
                        "for f in x; do echo $(( (1 + 2) * 3 )) ${#f}; done"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_deep_nesting_warns_instead_of_raising(self) -> None:
        # Unlinked finding shell_parse.py:390: the lexer located each closing
        # ")" with a fresh lexer per level before parse_shell could check
        # MAX_DEPTH, so 1,200 levels raised RecursionError out of the lint.
        levels = 1200
        for command in ("echo " + "$(" * levels + "true" + ")" * levels,
                        "echo " + "$(" * levels,
                        "echo " + "${X:-" * levels + "y" + "}" * levels,
                        "echo " + "$((" * levels + "1" + "))" * levels):
            with self.subTest(command=command[:12]):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("nesting deeper than 32", hits[0].message)

    def test_deep_find_exec_chain_does_not_raise(self) -> None:
        # shell_guard._expanded recursed once per nested find -exec body, with no bound.
        command = "for f in a; do " + "find . -exec " * 1200 + "rm -f x; done"
        hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
        self.assertIn("loop", hits[0].message)

    def test_inner_mutator_is_found_through_nested_shells(self) -> None:
        # The depth tracking keeps the innermost command of a real chain.
        command = "for f in a; do " + _nested_sh_c("rm -f x", 3) + "; done"
        self.assertIn("loop", self.assert_fires(_workflow(_stage(f"Run:\n\n  {command}\n")))[0].message)

    def test_read_only_qualified_shell_forms_are_silent(self) -> None:
        # Happy path: a read-only -c string, a script file (command semantics,
        # out of the guard's reach), and a qualified shell outside a loop.
        for command in ("for f in a; do /bin/sh -c 'wc -l x'; done",
                        "for f in a; do /bin/bash script.sh; done",
                        "/bin/sh -c 'rm -f x'",
                        "echo eval sh -c"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_fires_on_expanding_heredoc_inside_qualified_shell_string(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV66q: a path-qualified `sh -c` passes
        # the bare-shell check, and the heredoc inside its string was dropped
        # when the string was expanded, so the refused heredoc went unreported.
        for command in ("/bin/sh -c 'cat <<EOF\n  $(date)\n  EOF\n  '",
                        "for f in a; do /bin/bash -c 'cat <<EOF\n  `date`\n  EOF\n  '; done"):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("heredoc", hits[0].message)

    def test_quoted_heredoc_inside_qualified_shell_string_is_silent(self) -> None:
        # Happy path: a quoted delimiter keeps the inner body inert.
        command = "/bin/sh -c 'cat <<\"EOF\"\n  $(date)\n  EOF\n  '"
        self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_fires_on_escaped_backtick_nested_in_backticks(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV67M: the outer backtick body kept
        # its backslashes, so the inner \`rm -f x\` never ran as a command.
        desc = "Run:\n\n  for f in a; do echo `echo \\`rm -f x\\``; done\n"
        self.assertIn("loop", self.assert_fires(_workflow(_stage(desc)))[0].message)

    def test_read_only_backtick_substitution_in_loop_is_silent(self) -> None:
        for desc in ("Run:\n\n  for f in a; do echo `wc -l x`; done\n",
                     "Run:\n\n  for f in a; do echo `echo \\`wc -l x\\``; done\n"):
            with self.subTest(desc=desc):
                self.assert_silent(_workflow(_stage(desc)))

    def test_fires_on_env_split_string_anywhere(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV67e: h_env refuses -S/--split-string
        # outright, loop or not, since the string it splits is the command line.
        for command in ('env -S "rm -f x"', 'for f in a; do env -S "rm -f x"; done',
                        'env --split-string="rm -f x"', 'env -iS "wc -l x"', 'sudo env --split "ls"'):
            with self.subTest(command=command):
                hits = self.assert_fires(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))
                self.assertIn("env -S", hits[0].message)

    def test_env_without_split_string_is_silent(self) -> None:
        for command in ("env FOO=1 ls", "env -uS ls", "for f in a; do env FOO=1 wc -l x; done"):
            with self.subTest(command=command):
                self.assert_silent(_workflow(_stage(f"Run:\n\n  ```bash\n  {command}\n  ```\n")))

    def test_has_teeth(self) -> None:
        self.assert_has_teeth(_workflow(_stage(_LOOP)))


if __name__ == "__main__":
    unittest.main()
