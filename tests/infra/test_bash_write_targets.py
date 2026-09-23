"""Unit tests for .claude/hooks/_bash_write_targets.py, the Bash-branch parser.

The hook suites (block-readonly-role-writes.test.sh, guard-contract.test.sh) judge the
analyser and classify_path together, end to end. These pin the analyser ALONE: which
paths it reports as write targets, and which commands it refuses as unknowable. A
regression here shows up as a named record rather than as a flipped verdict three
layers away.

Loaded by file path, not imported: the analyser lives beside the hook scripts and is
run as `python3 -I -S <file>`, never as a package.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess  # nosec B404 - runs the in-repo analyser with a fixed argv
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import repo_root

ANALYSER = repo_root() / ".claude" / "hooks" / "_bash_write_targets.py"

_spec = importlib.util.spec_from_file_location("_bash_write_targets", ANALYSER)
assert _spec is not None and _spec.loader is not None  # nosec B101 - fixed in-repo path
bwt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bwt)


def records(command: str, root: str = "") -> tuple[list[str], list[str]]:
    """(targets, refusals) for one command. Targets are 'T1path' / 'T0path'."""
    sink = bwt.analyse_command(command, root)
    return sink.records, sink.unknowns


class TargetsTest(unittest.TestCase):
    """Each row is one grammar rule the old string scanner got wrong at least once."""

    CASES = [
        # Redirect operators, parsed as operators rather than characters.
        ("echo x > src/a.py", ["T1src/a.py"]),
        ("echo x >> src/a.py", ["T1src/a.py"]),
        ("echo x >| src/a.py", ["T1src/a.py"]),
        ("echo x >&src/a.py", ["T1src/a.py"]),
        ("echo x &> src/a.py", ["T1src/a.py"]),
        ("echo x 1<> src/a.py", ["T1src/a.py"]),
        ("exec 3>src/a.py", ["T1src/a.py"]),
        # A descriptor is not a filename.
        ("make test 2>&1", []),
        ("cmd 1>&2", []),
        ("make test >&1", []),
        ("cmd >&-", []),
        # A separator glued to the target ends the word.
        ("echo x >AGENTS.md; make test", ["T1AGENTS.md"]),
        ("echo x >CLAUDE.md&&true", ["T1CLAUDE.md"]),
        ("echo x >Makefile|cat", ["T1Makefile"]),
        # Quoting: one word, quotes removed; "a"b'c' is abc.
        ("rm -rf 'src'", ["T0src"]),
        ('rm -rf "src"', ["T0src"]),
        ("""rm -rf "s"r'c'""", ["T0src"]),
        ("rm -rf s\\rc", ["T0src"]),
        ("rm -rf $'\\x73rc'", ["T0src"]),
        ('echo x > "/tmp/a b.json"', ["T1/tmp/a b.json"]),
        # Brace and tilde expansion are static, so they are performed.
        ("rm -rf {src,x}", ["T0src", "T0x"]),
        ("{rm,-rf,src}", ["T0src"]),
        # Nested groups. PR #408's review claimed these stay literal; bash expands
        # each to three words, and so must the analyser, or `rm -rf` hides src.
        ("rm -rf {src,{tests,bin}}", ["T0src", "T0tests", "T0bin"]),
        ("rm -rf {{src,tests},bin}", ["T0src", "T0tests", "T0bin"]),
        ("rm -rf x{a,{b,src}}", ["T0xa", "T0xb", "T0xsrc"]),
        ("rm -rf {{a..c},src}", ["T0a", "T0b", "T0c", "T0src"]),
        # Depth 3 is the case with teeth: words are brace-expanded once per command
        # and again per target, so two levels expand even if brace_expand stopped
        # recursing. Only a third level proves the recursion itself.
        ("rm -rf {a,{b,{src,c}}}", ["T0a", "T0b", "T0src", "T0c"]),
        # ...and where bash does NOT expand, neither may the analyser: a group with
        # no top-level comma, or a quoted/escaped comma, stays one literal word.
        ("rm -rf {{src,tests}}", ["T0{src}", "T0{tests}"]),
        ("rm -rf '{src,x}'", ["T0{src,x}"]),
        ("rm -rf {src\\,x}", ["T0{src,x}"]),
        # Options: attached, glued long, prefix long, clusters, and --.
        ("cp -t src /tmp/e.py", ["T1src"]),
        ("cp --target-directory=src /tmp/e.py", ["T1src"]),
        ("cp --target=src /tmp/e.py", ["T1src"]),
        ("install -tsrc /tmp/e.py", ["T1src"]),
        ("ln -tsrc /tmp/x", ["T1src", "T0/tmp/x"]),       # -t's value is not -s
        ("ln -vs src/a.py /tmp/l", ["T1/tmp/l"]),          # a real -s cluster
        ("truncate -s 0 /tmp/log", ["T1/tmp/log"]),       # 0 is -s's value
        ("touch -t 202301010000 /tmp/x", ["T1/tmp/x"]),
        ("rm -- -probe.py", ["T0-probe.py"]),
        # Reads through mutating commands are not targets.
        ("cp src/a.py /tmp/c.py", ["T1/tmp/c.py"]),
        ("sed -n '1,5p' src/a.py", []),
        ("sed -e 's/a/b/' src/a.py", []),
        ("dd if=src/a.py of=/tmp/o", ["T1/tmp/o"]),
        # In-place sed, whatever the spelling.
        ("sed -i '' 's/a/b/' src/a.py", ["T0src/a.py"]),
        ("sed -iE 's/a/b/' src/a.py", ["T0src/a.py"]),
        ("sed -Ei 's/a/b/' src/a.py", ["T0src/a.py"]),
        ("sed -n -i 's/a/b/' src/a.py", ["T0src/a.py"]),
        ("sed --in-place 's/a/b/' src/a.py", ["T0src/a.py"]),
        # Hard links alias the inode: every operand counts.
        ("ln src/a.py /tmp/out", ["T0src/a.py", "T0/tmp/out"]),
        # Every separator starts a new command, and its command word is judged.
        ("cat README.md\nrm -rf src", ["T0src"]),
        ("cat README.md & rm -rf src", ["T0src"]),
        ("cat README.md | tee src/a.py", ["T1src/a.py"]),
        # Reserved words are not command names.
        ("for f in a b; do rm -rf src; done", ["T0src"]),
        ("if true; then rm -rf src; fi", ["T0src"]),
        ("while false; do touch src/x; done", ["T1src/x"]),
        ("case x in a) rm -rf src;; esac", ["T0src"]),
        ("f() { rm -rf src; }", ["T0src"]),
        ("( cd /tmp && rm -rf src )", ["T0src"]),
        ("{ echo x; } > src/x", ["T1src/x"]),
        ("time -p rm -rf src", ["T0src"]),
        # Inside [[ ]] and (( )), < and > compare; they do not redirect.
        ("[[ a > b ]] && echo ok", []),
        ("(( x > 3 )) && echo ok", []),
        # Substitution bodies RUN, whatever position they sit in.
        ("cat $(rm -rf src)", ["T0src"]),
        ("cat `rm -rf src`", ["T0src"]),
        ('echo "$(touch src/x)"', ["T1src/x"]),
        ("cat <(rm -rf src)", ["T0src"]),
        ("tee >(cat > src/x) < /tmp/y", ["T1src/x"]),
        ("a=(1 $(rm -rf src))", ["T0src"]),
        ("x=$(case y in a) echo hi;; esac)", []),
        # Heredocs: the body is data unless an unquoted delimiter lets $(...) run.
        ("cat <<'EOF' > /tmp/o\nrm -rf src > src/x\nEOF", ["T1/tmp/o"]),
        ("cat <<EOF\n$(rm -rf src)\nEOF", ["T0src"]),
        # Wrappers run the command that follows them.
        ("env FOO=1 rm -rf src", ["T0src"]),
        ("nohup rm -rf src", ["T0src"]),
        ("timeout 5 rm -rf src", ["T0src"]),
        ("command rm -rf src", ["T0src"]),
        ("bash -c 'rm -rf src'", ["T0src"]),
        ("bash +o posix -c 'rm -rf src'", ["T0src"]),
        ("eval 'rm -rf src'", ["T0src"]),
        ("find src -exec rm {} +", ["T0src"]),
        ("find /tmp/ws -name '*.json' -delete", ["T0/tmp/ws"]),
        # Not mutators: no targets.
        ("cat src/a.py", []),
        ("grep --include=*.py -rn X src/", []),
        ('"$ROOT/bin/workflow" list', []),
        ("echo x # > src/x", []),
    ]

    def test_targets(self) -> None:
        for command, expected in self.CASES:
            with self.subTest(command=command):
                targets, refusals = records(command)
                self.assertEqual(refusals, [], msg=command)
                self.assertEqual(targets, expected, msg=command)

    def test_tilde_expands_to_home(self) -> None:
        home = str(Path.home())
        targets, _ = records("echo x > ~/probe")
        self.assertEqual(targets, [f"T1{home}/probe"])

    def test_glob_target_reports_its_directory_and_matches(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            Path(root, "src").mkdir()
            Path(root, "sig").mkdir()
            Path(root, "other").mkdir()
            targets, refusals = records("rm -rf s*", root)
        self.assertEqual(refusals, [])
        # "." -- the directory the glob lives in -- is the repo root for a relative
        # path, so `rm -rf s*` is judged as touching it, plus each match.
        self.assertEqual(targets[0], "T0.")
        self.assertEqual(sorted(targets[1:]), [f"T0{root}/sig", f"T0{root}/src"])


class RefusalsTest(unittest.TestCase):
    """Fail closed: what cannot be known before the shell runs is refused, by name."""

    CASES = [
        ("P=src/a.py; echo x > $P", "a variable"),
        ("echo x > src${IFS}/a.py", "a parameter expansion"),
        ("echo x > $(pick)", "a command substitution"),
        ("echo x > $((1+2))", "an arithmetic expansion"),
        ("echo x >&$fd", "a variable"),
        ("$CMD src/x", "command name"),
        ("/bin/r? -rf src", "command name"),
        ('eval "$CMD"', "eval"),
        ("echo 'rm -rf src' | bash", "stdin"),
        ("xargs rm < /tmp/list", "rm"),
        ('cp "$f" /tmp/ws/', "cp"),            # "$f" may be --target-directory=src
        ('sed -n "$r" src/a.py', None),       # "$r" may be -i
        ('find . -name "$p"', "find"),         # "$p" may be -delete
        ("dd $X", "dd"),
        ("env -S 'rm -rf src'", "env -S"),
        ("patch -p1 < fix.patch", "patch"),
        ("echo 'unterminated", "could not be parsed"),
        ("echo $(unterminated", "could not be parsed"),
        ("echo x )", "could not be parsed"),
        ("echo x > =ls", "zsh"),
    ]

    def test_refusals(self) -> None:
        for command, fragment in self.CASES:
            with self.subTest(command=command):
                targets, refusals = records(command)
                if fragment is None:
                    # Not refused: judged as if the unknown word were -i, so the
                    # source operand comes back as a target instead.
                    self.assertIn("T0src/a.py", targets)
                    continue
                self.assertTrue(refusals, msg=f"not refused: {command!r} -> {targets}")
                self.assertIn(fragment, " ".join(refusals))

    def test_unknown_words_in_read_positions_are_fine(self) -> None:
        # Refusing every variable would make the role useless; only positions that
        # can decide a write matter.
        for command in ('cat "$f"', 'grep "$pat" src/', "wc -l $(git ls-files)",
                        'for f in src/*.py; do wc -l "$f"; done', 'cp src/a.py "/tmp/x"'):
            with self.subTest(command=command):
                _, refusals = records(command)
                self.assertEqual(refusals, [])


class ProtocolTest(unittest.TestCase):
    """The wire format the hook reads. An absent OK is how a crash reads as a block."""

    def _run(self, stdin: bytes) -> list[bytes]:
        proc = subprocess.run(  # nosec B603 - fixed argv, in-repo script
            [sys.executable, "-I", "-S", str(ANALYSER), str(repo_root())],
            input=stdin,
            capture_output=True,
            check=True,
            timeout=30,
        )
        out = proc.stdout
        self.assertTrue(out.endswith(b"\0"), msg=out)
        return out[:-1].split(b"\0")

    def test_ok_is_the_final_record(self) -> None:
        recs = self._run(json.dumps({"tool_input": {"command": "echo x > /tmp/o"}}).encode())
        self.assertEqual(recs, [b"T1/tmp/o", b"OK"])

    def test_a_newline_in_a_path_survives(self) -> None:
        recs = self._run(json.dumps({"tool_input": {"command": "echo x > '/tmp/a\nb'"}}).encode())
        self.assertEqual(recs, [b"T1/tmp/a\nb", b"OK"])

    def test_malformed_input_is_a_refusal_not_a_crash(self) -> None:
        for stdin in (b"not json", b"{}", json.dumps({"tool_input": {"command": 7}}).encode()):
            with self.subTest(stdin=stdin):
                recs = self._run(stdin)
                self.assertEqual(recs[-1], b"OK")
                self.assertTrue(recs[0].startswith(b"U"), msg=recs)


if __name__ == "__main__":
    unittest.main()
