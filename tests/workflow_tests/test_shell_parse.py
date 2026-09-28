"""Tests for the shell command parser (workflow.shell_parse).

The shared simple-command model every shell lint rule reads.
"""

from __future__ import annotations

import unittest

from workflow.shell_parse import parse_shell
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
        self.assertEqual(script.loop_variables, ("f",))

    def test_redirect_classification(self) -> None:
        cmd = parse_shell('x 2>&1 >&- < in 3<>rw > "o" >> a &> b <<< s').commands[0]
        self.assertEqual([(r.op, r.writes) for r in cmd.redirects], [
            (">&", False), (">&", False), ("<", False), ("<>", True), (">", True),
            (">>", True), ("&>", True), ("<<<", False),
        ])
        test = parse_shell('[[ "$a" > b ]] && [[ -n x ]]').commands
        self.assertEqual(test, ())

    def test_labelled_assignment_is_extracted_outside_segments_only(self) -> None:
        desc = "Bash tool: F=\"x\"\n```bash\nNote: G=1\n```\ncat <<'EOF'\nLabel: H=1\nEOF\n"
        self.assertEqual([s.text for s in extract_labelled_assignments(desc)], ['F="x"'])


if __name__ == "__main__":
    unittest.main()
