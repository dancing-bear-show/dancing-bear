"""Tests for the shell command parser (workflow.shell_parse).

The shared simple-command model every shell lint rule reads.
"""

from __future__ import annotations

import unittest

from workflow.shell_parse import WRAPPER_NAMES, LoopVariable, command_from_words, parse_shell
from workflow.shell_text import extract_labelled_assignments


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


if __name__ == "__main__":
    unittest.main()
