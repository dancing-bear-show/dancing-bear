"""Tests for the shell command parser (workflow.shell_parse).

The shared simple-command model every shell lint rule reads.
"""

from __future__ import annotations

import subprocess  # nosec B404 - runs this interpreter on a fixed import statement
import sys
import unittest
from pathlib import Path

import workflow.shell_parse as shell_parse
import workflow.shell_text as shell_text
from workflow.shell_parse import (
    MAX_DEPTH,
    MAX_EXPANSION_NEST,
    WRAPPER_NAMES,
    LoopVariable,
    command_from_words,
    parse_shell,
)
from workflow.shell_text import extract_labelled_assignments, is_command_line


class TestParseShell(unittest.TestCase):
    """The shared simple-command model every rule reads."""

    def _names(self, text: str) -> list[str]:
        return [cmd.name for cmd in parse_shell(text).commands]

    def test_command_word_follows_separators_keywords_and_wrappers(self) -> None:
        cases = {
            "a; b && c || d | e & f": ["a", "b", "c", "d", "e", "f"],
            "if x; then y; elif z; then w; else v; fi": ["x", "y", "z", "w", "v"],
            "while ! t; do { u; }; done": ["t", "u"],
            "(cd src && make)": ["cd", "make"],
            "FOO=1 BAR=2 env -u X BAZ=3 nice -n 5 timeout -s KILL 10 /bin/rm x": ["rm"],
            "time -p sudo -u me xargs -I {} cp {} dst": ["cp"],
            "echo rm python3 check-params": ["echo"],
            "command -v rm": [""],
        }
        for text, names in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._names(text), names)

    def test_substitutions_are_parsed_as_commands(self) -> None:
        # `date`'s output is the outer command's program word.
        self.assertEqual(
            self._names('X="$(jq -r .a f)" `date` <(sort f) "${Y:-z}"'),
            ["`date`", "jq", "date", "sort"],
        )

    def test_heredoc_body_is_data_not_commands(self) -> None:
        script = parse_shell("cat <<'EOF'\nrm -rf /\nFOO=1\nEOF\ncat <<EOF\n$(date)\nEOF\necho done")
        self.assertEqual([cmd.name for cmd in script.commands], ["cat", "cat", "echo", "date"])
        self.assertEqual([(d.quoted, d.body) for d in script.heredocs],
                         [(True, "rm -rf /\nFOO=1\n"), (False, "$(date)\n")])

    def test_indented_delimiter_does_not_close_a_heredoc(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6njyv1: the closer was matched after
        # strip(), so `  EOF` ended the body early and the lines after it were
        # parsed as live commands. Bash needs the exact line for <<EOF, and
        # strips only tabs, never spaces, for <<-EOF.
        for text in ("cat <<EOF\n  EOF\nrm -rf x\nEOF\necho done", "cat <<-EOF\n  EOF\nrm -rf x\nEOF\necho done"):
            with self.subTest(text=text):
                script = parse_shell(text)
                self.assertEqual([c.name for c in script.commands], ["cat", "echo"])
                self.assertEqual([d.body for d in script.heredocs], ["  EOF\nrm -rf x\n"])

    def test_tab_indented_delimiter_closes_a_dash_heredoc(self) -> None:
        script = parse_shell("cat <<-EOF\n\tbody\n\t\tEOF\necho done")
        self.assertEqual([c.name for c in script.commands], ["cat", "echo"])
        self.assertEqual([(d.body, d.strip_tabs) for d in script.heredocs], [("\tbody\n", True)])
        # Without the dash a tab-indented closer is body data, like a space-indented one.
        script = parse_shell("cat <<EOF\n\tEOF\necho x\nEOF\n")
        self.assertEqual([(d.body, d.strip_tabs) for d in script.heredocs], [("\tEOF\necho x\n", False)])

    def test_unconditional_marks_commands_whose_status_can_stop_the_shell(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6njyuA: a check-params whose failure
        # is masked validates nothing. Judged within each command's own shell.
        cases = {
            "a; b && c": [("a", True), ("b", True), ("c", True)],
            "a | b": [("a", False), ("b", False)],
            "! a; b": [("a", False), ("b", True)],
            "a || b; c": [("a", False), ("b", False), ("c", True)],
            "a || exit 1": [("a", True), ("exit", False)],
            "a &": [("a", False)],
            "if a; then b; fi; c": [("a", False), ("b", False), ("c", True)],
            "while a; do b; done; c": [("a", False), ("b", False), ("c", True)],
            "for x in y; do a; done; b": [("a", False), ("b", True)],
            "case x in y) a ;; esac; b": [("a", False), ("b", True)],
            "f() { a; }; { b; }; c": [("a", False), ("b", False), ("c", True)],
            'echo "$(a; b)"': [("echo", True), ("a", True), ("b", True)],
        }
        for text, flags in cases.items():
            with self.subTest(text=text):
                self.assertEqual([(c.name, c.unconditional) for c in parse_shell(text).commands], flags)

    def test_comment_spans(self) -> None:
        # A `#` that begins a word, outside quotes and heredoc bodies, runs to
        # the end of its line. Offsets include a nested substitution's base.
        cases: dict[str, list[str]] = {
            "echo ok # {host} $UNBOUND": ["# {host} $UNBOUND"],
            "echo a;#x\necho b": ["#x"],
            "X=$(echo a # in sub\n)": ["# in sub"],
            "echo a#b ${#x} $FOO#bar": [],
            "echo '# q' \"# dq\" \\#esc": [],
            "cat <<'EOF'\n# body\nEOF\ncat <<EOF\n# body\nEOF": [],
        }
        for text, comments in cases.items():
            with self.subTest(text=text):
                spans = parse_shell(text).comments
                self.assertEqual([text[lo:hi] for lo, hi in spans], comments)

    def test_loop_membership_and_bindings(self) -> None:
        script = parse_shell('for f in a; do rm "$f"; done; mv a b\nwhile read -r L; do :; done')
        self.assertEqual([(c.name, c.in_loop) for c in script.commands],
                         [("rm", True), ("mv", False), ("read", False), (":", True)])
        self.assertEqual(script.loop_variables, (LoopVariable("f"),))

    def _scopes(self, text: str) -> list[tuple[str, tuple[int, int] | None]]:
        """(first assignment or program word, child-shell span) per command, in parse order."""
        return [
            ((cmd.assignments[0].text if cmd.assignments else cmd.name), cmd.subshell)
            for cmd in parse_shell(text).commands
        ]

    def test_commands_in_child_shells_record_their_span(self) -> None:
        # PR #433 review: commands in $(...) were flattened into
        # script.commands with nothing marking them as a child shell.
        cases = {
            'echo "$(FOO=bar true)"; echo "$FOO"': [("echo", None), ("echo", None), ("FOO=bar", (8, 20))],
            "echo `FOO=1 true`": [("echo", None), ("FOO=1", (6, 16))],
            "diff <(Q=1 sort a) b": [("diff", None), ("Q=1", (7, 17))],
            "cat <<EOF\n$(Z=1 true)\nEOF\n": [("cat", None), ("Z=1", (12, 20))],
            '( FOO=1 ); echo "$FOO"': [("FOO=1", (0, 9)), ("echo", None)],
        }
        for text, scopes in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._scopes(text), scopes)

    def test_nested_groups_keep_the_innermost_span(self) -> None:
        self.assertEqual(
            self._scopes("( A=1; ( B=2 ); C=3 ); D=4"),
            [("A=1", (0, 21)), ("B=2", (7, 14)), ("C=3", (0, 21)), ("D=4", None)],
        )

    def test_parent_shell_constructs_are_not_child_shells(self) -> None:
        # Brace groups, function bodies, loop and if bodies run in the
        # current shell; a function definition's ( ) opens no group.
        cases = [
            "{ FOO=1; }",
            "f() { FOO=1; }",
            "for x in a; do FOO=1; done",
            "if true; then FOO=1; fi",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual({cmd.subshell for cmd in parse_shell(text).commands}, {None})

    def test_loop_variable_records_its_child_shell(self) -> None:
        script = parse_shell("( for V in a; do :; done ); for W in b; do :; done")
        self.assertEqual(script.loop_variables, (LoopVariable("V", (0, 26)), LoopVariable("W")))

    def test_redirect_classification(self) -> None:
        cmd = parse_shell('x 2>&1 >&- < in 3<>rw > "o" >> a &> b <<< s').commands[0]
        self.assertEqual([(r.op, r.writes) for r in cmd.redirects], [
            (">&", False), (">&", False), ("<", False), ("<>", True), (">", True),
            (">>", True), ("&>", True), ("<<<", False),
        ])
        test = parse_shell('[[ "$a" > b ]] && [[ -n x ]]').commands
        self.assertEqual(test, ())

    def test_command_from_words_resolves_wrappers(self) -> None:
        # find -exec hands on argv, not shell text: the program is still the
        # word after any wrappers, and env's assignments are recorded.
        words = parse_shell("env FOO=1 timeout 5 rm -f {}").commands[0].words
        cmd = command_from_words(words, in_loop=True)
        self.assertEqual((cmd.name, cmd.args, cmd.in_loop), ("rm", ["-f", "{}"], True))
        self.assertEqual([tok.text for tok in cmd.assignments], ["FOO=1"])
        self.assertEqual(command_from_words(parse_shell("command -v rm").commands[0].words).name, "")

    def test_every_wrapper_name_is_seen_through(self) -> None:
        # WRAPPER_NAMES is the vocabulary shell_text uses to extract
        # wrapper-led lines; each name must really hand on to its command.
        for name in sorted(WRAPPER_NAMES):
            head = f"{name} 5" if name.endswith("timeout") else name  # the duration operand
            with self.subTest(name=name):
                self.assertEqual(self._names(f"{head} rm x"), ["rm"])

    def test_labelled_assignment_is_extracted_outside_segments_only(self) -> None:
        desc = "Bash tool: F=\"x\"\n```bash\nNote: G=1\n```\ncat <<'EOF'\nLabel: H=1\nEOF\n"
        self.assertEqual([s.text for s in extract_labelled_assignments(desc)], ['F="x"'])

    def test_escaped_backtick_in_a_backtick_body_opens_a_nested_substitution(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV67M: the body kept its backslashes,
        # so \`rm -f x\` stayed a literal word and rm was never a command. The
        # guard's _read_backtick removes the escape before parsing the body.
        for text in ("echo `echo \\`rm -f x\\``", 'echo "`echo \\`rm -f x\\``"'):
            with self.subTest(text=text):
                script = parse_shell(text)
                self.assertEqual([(c.name, c.depth) for c in script.commands],
                                 [("echo", 0), ("echo", 1), ("rm", 2)])

    def test_backtick_body_decodes_only_the_guard_escapes(self) -> None:
        # Only a backtick, a backslash and $ lose their backslash (plus " inside
        # double quotes); \n, and \" outside double quotes, keep it.
        cases = {
            "echo `printf \\\\n`": "printf \\n",
            "echo `echo \\$HOME`": "echo $HOME",
            "echo `echo a\\nb`": "echo a\\nb",
            'echo `echo \\"x\\"`': 'echo \\"x\\"',
            'echo "`echo \\"x\\"`"': 'echo "x"',
        }
        for text, body in cases.items():
            with self.subTest(text=text):
                words = [w for c in parse_shell(text).commands for w in c.words if w.subs]
                self.assertEqual(words[0].subs[0][0], body)

    def test_env_split_string_is_recorded_not_resolved(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV67e: -S was read as an ordinary
        # value option, so `env -S "rm -f x"` ran nothing and passed silently.
        for text in ('env -S "rm -f x"', "env -Srm", 'env -iS "rm -f x"', 'env --split-string="rm -f x"',
                     'env --split-string "rm -f x"', 'env --split "rm -f x"', 'sudo env -S "rm -f x"',
                     'env -i FOO=1 env -S "rm -f x"'):
            with self.subTest(text=text):
                cmd = parse_shell(text).commands[0]
                self.assertTrue(cmd.split_string)
                self.assertIsNone(cmd.word)

    def test_env_without_split_string_resolves_as_before(self) -> None:
        # -u takes the S as its value; after an operand, -S is the command's.
        for text, name in (("env FOO=1 ls", "ls"), ("env -uS ls", "ls"), ("env -u S ls", "ls"),
                           ("env FOO=1 grep -S x", "grep"), ("env -- ls -S", "ls")):
            with self.subTest(text=text):
                cmd = parse_shell(text).commands[0]
                self.assertFalse(cmd.split_string)
                self.assertEqual(cmd.name, name)



class TestParseDepth(unittest.TestCase):
    """Nesting depth as the Bash guard counts it (_bash_write_targets.py MAX_DEPTH)."""

    @staticmethod
    def _subs(levels: int) -> str:
        text = "wc -l x"
        for _ in range(levels):
            text = f"echo $({text})"
        return text

    def test_each_substitution_is_one_level(self) -> None:
        script = parse_shell("a $(b `c`) <(d)")
        self.assertEqual({c.name: c.depth for c in script.commands}, {"a": 0, "b": 1, "c": 2, "d": 1})
        self.assertEqual(script.max_depth, 2)
        self.assertFalse(script.too_deep)

    def test_nesting_past_max_depth_is_recorded_not_dropped(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nH40K: past MAX_DEPTH parsing stops,
        # and the result says so, so a caller can refuse it as the guard does.
        at_limit, past = parse_shell(self._subs(MAX_DEPTH)), parse_shell(self._subs(MAX_DEPTH + 1))
        self.assertFalse(at_limit.too_deep)
        self.assertIn("wc", [c.name for c in at_limit.commands])
        self.assertTrue(past.too_deep)
        self.assertEqual(past.max_depth, MAX_DEPTH + 1)

    def test_substitution_inside_an_expansion_is_a_child_command(self) -> None:
        # Unlinked finding shell_parse.py:364: ${...} and $((...)) bodies are
        # scanned for $(...) and backticks, one level deeper, as the guard's
        # _scan_param/_scan_arith do.
        for text in ('echo "${X:-$(rm -f x)}"', "echo $(( $(rm -f x) ))", "(( $(rm -f x) ))",
                     "echo ${X:-`rm -f x`}", 'echo "$(( ${#a} + $(rm -f x) ))"'):
            with self.subTest(text=text):
                script = parse_shell(text)
                self.assertEqual({c.name: c.depth for c in script.commands if c.name == "rm"}, {"rm": 1})
                self.assertEqual(script.max_depth, 1)

    def test_expansion_nesting_counts_toward_the_substitution_depth(self) -> None:
        # A $(...) in an expansion in a $(...) is two parsers deep, as in the guard.
        script = parse_shell("echo $(echo ${X:-$(rm -f x)})")
        self.assertEqual({c.name: c.depth for c in script.commands}, {"echo": 1, "rm": 2})

    def test_expansion_without_substitution_has_no_child(self) -> None:
        for text in ("echo ${X:-default}", "echo $(( (1 + 2) * 3 ))", "(( i++ ))", "echo ${#a}"):
            with self.subTest(text=text):
                script = parse_shell(text)
                self.assertEqual(script.max_depth, 0)
                self.assertNotIn("rm", [c.name for c in script.commands])

    def test_deep_nesting_is_too_deep_not_an_exception(self) -> None:
        # Unlinked finding shell_parse.py:390: 1,200 nested $( raised
        # RecursionError before parse_shell could check MAX_DEPTH.
        n = 1200
        for text in ("$(" * n + "true" + ")" * n, "$(" * n):
            with self.subTest(text=text[:12]):
                self.assertTrue(parse_shell(text).too_deep)

    def test_deep_expansion_nesting_is_too_nested_not_an_exception(self) -> None:
        # ${...} and arithmetic are bounded by MAX_EXPANSION_NEST, not by the
        # guard's MAX_DEPTH: past it the rest is unread and reported.
        n = 1200
        for text in ("${X:-" * n + "}" * n, '"${X:-' * n, "$((" * n + "1" + "))" * n,
                     "echo $(" + "${X:-" * n + ")"):
            with self.subTest(text=text[:12]):
                script = parse_shell(text)
                self.assertTrue(script.too_nested)
                self.assertFalse(script.too_deep)

    def test_33_nested_parameter_expansions_are_not_too_deep(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6njyvT: the guard reads ${...} and
        # $((...)) in the same Parser (_scan_param, _scan_arith), so they never
        # count toward its MAX_DEPTH; 33 of them were reported "deeper than 32".
        for text in ("echo " + "${X:-" * (MAX_DEPTH + 1) + "}" * (MAX_DEPTH + 1),
                     "echo " + "$((" * (MAX_DEPTH + 1) + "1" + "))" * (MAX_DEPTH + 1),
                     "echo $(echo " + "${X:-" * (MAX_DEPTH + 1) + "}" * (MAX_DEPTH + 1) + ")"):
            with self.subTest(text=text[:12]):
                script = parse_shell(text)
                self.assertFalse(script.too_deep)
                self.assertFalse(script.too_nested)

    def test_expansion_nesting_bound_is_max_expansion_nest(self) -> None:
        at_limit = "echo " + "${X:-" * MAX_EXPANSION_NEST + "}" * MAX_EXPANSION_NEST
        past = "echo " + "${X:-" * (MAX_EXPANSION_NEST + 1) + "}" * (MAX_EXPANSION_NEST + 1)
        self.assertFalse(parse_shell(at_limit).too_nested)
        self.assertTrue(parse_shell(past).too_nested)

    def test_substitutions_still_count_toward_max_depth(self) -> None:
        # Happy path for the split: 33 nested $( are still past the guard's limit.
        script = parse_shell(self._subs(MAX_DEPTH + 1))
        self.assertTrue(script.too_deep)
        self.assertFalse(script.too_nested)

    def test_depth_argument_offsets_the_count(self) -> None:
        script = parse_shell("a $(b)", depth=MAX_DEPTH)
        self.assertTrue(script.too_deep)
        self.assertEqual([c.name for c in script.commands], ["a"])
        self.assertEqual(command_from_words(script.commands[0].words, depth=5).depth, 5)

    def test_escaped_backtick_nesting_counts_toward_the_depth(self) -> None:
        # Decoded backtick bodies nest one parser deeper per level, as in the guard.
        text = "wc -l x"
        for _ in range(3):
            text = "echo `" + "".join("\\" + ch if ch in "`\\$" else ch for ch in text) + "`"
        self.assertEqual(parse_shell(text).max_depth, 3)


class TestShellTextImports(unittest.TestCase):
    """shell_text uses the parser under private names; it re-exports none of them."""

    def test_parser_names_are_not_importable_from_shell_text(self) -> None:
        # PR #437 thread PRRT_kwDOQr1kjM6nV68O: `from workflow.shell_text
        # import parse_shell` still worked through the public-named import.
        # Run as written, in a fresh isolated interpreter: a static import of
        # a missing name is also a type error, which is the point here.
        src = str(Path(shell_text.__file__).resolve().parents[1])
        code = f"import sys; sys.path.insert(0, {src!r}); from workflow.shell_text import parse_shell"
        result = subprocess.run(  # nosec B603 - this interpreter, a fixed import statement
            [sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImportError: cannot import name 'parse_shell'", result.stderr)
        for name in shell_parse.__all__:
            with self.subTest(name=name):
                self.assertFalse(hasattr(shell_text, name))

    def test_shell_text_still_uses_the_parser_internally(self) -> None:
        # The wrapper vocabulary and the parser behind it still drive extraction.
        self.assertTrue(is_command_line("env python3 runner"))
        self.assertTrue(is_command_line("timeout 5 ./bin/workflow lint x"))
        self.assertFalse(is_command_line("timeout to interrupt a handler"))


if __name__ == "__main__":
    unittest.main()
