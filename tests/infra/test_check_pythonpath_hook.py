"""The SessionStart PYTHONPATH warning must fire exactly when it should.

`.claude/scripts/check-pythonpath.sh` is the layer that covers a bare
``python3 -c`` — the one invocation neither ``bin/_router.py`` nor the Makefile
can intercept. Its value is entirely in which of three states it warns about, so
a parsing slip or a change to the hook's output contract would ship silently.

The hook must emit a single JSON object with a ``systemMessage`` key when
PYTHONPATH names a DIFFERENT checkout of this repo, and emit nothing at all
otherwise. It must never exit non-zero: a wrong PYTHONPATH is a correctness
hazard, not a reason to refuse to start a session.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess  # nosec B404 - runs this repo's own hook script, no user input
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "scripts" / "check-pythonpath.sh"


def _run_hook(pythonpath: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run(  # nosec B603 B607 - in-repo script, fixed argv
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )


#: The EXACT argv of the diagnostic the hook advises, as tokenized by
#: ``shlex.split``. ``test_the_advised_diagnostic_is_itself_safe`` runs this
#: command for real, so it is pinned rather than trusted: the hook is a tracked
#: file, and a branch that rewrote its advised line would otherwise turn this
#: suite into an execution sink for arbitrary code. Shape checks alone cannot
#: close that — ``-I -S`` isolates imports, it does not sandbox ``os.system``.
#:
#: Changing the hook's advised line SHOULD fail that test. Read the replacement
#: first, confirm it still resolves without importing, then update this list.
EXPECTED_DIAGNOSTIC_ARGV = [
    "python3",
    "-I",
    "-S",
    "-c",
    (
        "import importlib.util as u, os, sys; "
        "sys.path[:0] = os.environ.get('PYTHONPATH','').split(os.pathsep); "
        "s = u.find_spec('resume'); "
        "print(s.origin if s else 'not found')"
    ),
]


def _make_fake_checkout(root: Path) -> Path:
    """A decoy checkout of THIS project: src/ plus a matching pyproject.toml."""
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "personal-assistants"\nversion = "0.1.0"\n'
    )
    return root / "src"


def _make_third_party_checkout(root: Path) -> Path:
    """A DIFFERENT project that happens to have src/ and a pyproject.toml.

    This is the case a bare "has a pyproject.toml" heuristic gets wrong: most
    third-party checkouts have one, so matching on its presence alone would warn
    about paths we have no business touching.
    """
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "some-other-lib"\n')
    return root / "src"


# A python invocation is an executable FOLLOWED BY flags and then -c / -m / a
# script path. Requiring that tail is what separates a real launch from a
# `python3 -c` named inside a comment or a quoted warning message.
_PY_INVOCATION = re.compile(
    r"(?:^|[\s;&|(`$])"            # start, or a shell boundary
    r"(?:env\s+(?:-\S+\s+)*)?"     # optional `env [-flags]`
    r"(?:\.{0,2}[\w./-]*/)?"       # optional dir: /usr/bin/, ./.venv/bin/, ../x/
    r"python(?:3(?:\.\d+)?)?"      # python | python3 | python3.11
    r"((?:\s+-\S+)*)"              # captured: the flag run
    r"\s+(?:-c|-m\b|\S+\.py\b)"    # the payload that proves a launch
)


def _code_lines(text: str) -> list[str]:
    """Lines that can execute — comments and quoted blocks removed.

    Tracking shell quoting exactly would mean writing a parser. The cheap,
    reliable approximation: drop comment lines, then drop everything between an
    odd double-quote and its partner. That is what excludes
    check-pythonpath.sh, whose multi-line ``emit "..."`` warning names
    ``python3 -c`` twice in prose.
    """
    out: list[str] = []
    in_string = False
    for line in text.splitlines():
        if not in_string and line.lstrip().startswith("#"):
            continue
        quotes = line.count('"') - line.count('\\"')
        if in_string:
            if quotes % 2 == 1:
                in_string = False
            continue  # the whole line sits inside a string
        if quotes % 2 == 1:
            in_string = True
            line = line.split('"', 1)[0]  # keep only the code before it
        else:
            # Balanced quotes on this line: blank out each "..." span, so an
            # interpreter named inside `echo "run python3 -c ..."` is not read
            # as a launch. Done per line because a span that opens and closes
            # here cannot be part of the multi-line state above.
            line = re.sub(r'"[^"]*"', '""', line)
            line = re.sub(r"'[^']*'", "''", line)
        out.append(line.split(" #", 1)[0])
    return out


def _launches_unisolated_python(text: str) -> bool:
    """True if *text* launches python without both -I and -S.

    Checked statically rather than by running the hook. Executing hooks is not
    viable: WorktreeCreate creates a real git worktree and branch as a side
    effect, and name-worktree.sh sends its interpreter's stderr to /dev/null —
    so a planted payload executes while leaving no trace to observe. A probe
    blind to the defect it exists to catch is worse than no probe, and that
    exact blindness let an earlier version of this audit report OK with the
    WorktreeCreate hole open.
    """
    for line in _code_lines(text):
        for m in _PY_INVOCATION.finditer(line):
            flags = (m.group(1) or "").split()
            if "-I" not in flags or "-S" not in flags:
                return True
    return False


def _hook_sources(command: str) -> list[tuple[str, str]]:
    """The command itself, plus any in-repo shell script it invokes."""
    out = [(command[:70], command)]
    for m in re.finditer(r"(?:bash|sh|zsh)\s+(\S+\.sh)", command):
        script = REPO_ROOT / m.group(1)
        if script.is_file():
            out.append((m.group(1), script.read_text()))
    return out


class TestCheckPythonpathHook(unittest.TestCase):
    def test_warns_when_pythonpath_names_another_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))

            proc = _run_hook(str(foreign))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("systemMessage", payload)
            msg = payload["systemMessage"]
            self.assertIn(str(foreign), msg)
            # The message must name the remedy, not merely the problem.
            self.assertIn("direnv allow", msg)
            self.assertIn("make test", msg)

    def test_silent_when_pythonpath_is_this_checkout(self) -> None:
        proc = _run_hook(str(REPO_ROOT / "src"))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_silent_when_pythonpath_is_unset(self) -> None:
        proc = _run_hook(None)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_silent_for_an_unrelated_src_directory(self) -> None:
        """A ``src`` with no sibling pyproject.toml belongs to someone else.

        Warning about it would train the reader to ignore the warning.
        """
        with tempfile.TemporaryDirectory() as td:
            unrelated = Path(td, "some-lib", "src")
            unrelated.mkdir(parents=True)  # deliberately NO pyproject.toml

            proc = _run_hook(str(unrelated))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")

    def test_warns_when_a_foreign_entry_is_mixed_with_a_good_one(self) -> None:
        """A correct entry alongside a foreign one is still a hazard.

        Import order decides the winner, so the presence of our own src/ does
        not make the foreign entry harmless.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))
            mixed = os.pathsep.join([str(REPO_ROOT / "src"), str(foreign)])

            proc = _run_hook(mixed)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn(str(foreign), payload["systemMessage"])

    def test_silent_for_a_third_party_checkout_with_its_own_pyproject(self) -> None:
        """A pyproject.toml is not enough — it must name THIS project.

        Most third-party checkouts ship a pyproject.toml, so a presence-only
        marker would warn about unrelated paths and train the reader to ignore
        the warning.
        """
        with tempfile.TemporaryDirectory() as td:
            other = _make_third_party_checkout(Path(td, "some-other-lib"))

            proc = _run_hook(str(other))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")

    def test_no_interpreter_runs_with_the_foreign_path_still_set(self) -> None:
        """The hook must not start Python while the foreign PYTHONPATH is live.

        Python imports sitecustomize/usercustomize from PYTHONPATH entries during
        startup, so an interpreter launched here would execute code from the very
        checkout being warned about. Planting a sitecustomize.py proves whether
        the hook is exposed.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))
            (foreign / "sitecustomize.py").write_text(
                'import sys; sys.stderr.write("PWNED\\n")\n'
            )

            proc = _run_hook(str(foreign))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("PWNED", proc.stderr)
            self.assertNotIn("PWNED", proc.stdout)
            # The warning itself must still be emitted.
            self.assertIn("systemMessage", json.loads(proc.stdout))

    def test_no_configured_hook_starts_an_unisolated_interpreter(self) -> None:
        """NO hook of ANY type may start a Python interpreter without -I -S.

        Hook processes inherit the session's environment, which is exactly when
        PYTHONPATH may name a foreign checkout. Python imports
        sitecustomize/usercustomize from PYTHONPATH entries during startup, so a
        bare interpreter in a hook executes code from that checkout before the
        hook does anything.

        This audit has been widened twice, each time because it was scoped to
        what had just been fixed rather than to the property it defends:

          - v1 tested only check-pythonpath.sh, so the SessionStart hook ordered
            AHEAD of it kept the exposure open.
          - v2 covered SessionStart only and matched commands that literally
            START with "python3", so the WorktreeCreate hook — and any
            ``/usr/bin/python3``, ``env python3``, or interpreter appearing
            mid-command — sailed through.

        It now walks every hook type in settings.json and follows ``bash
        <script>`` references into the repo.
        """
        settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())

        offenders = [
            f"{hook_type}: {label}"
            for hook_type, groups in settings.get("hooks", {}).items()
            for group in groups
            for hook in group.get("hooks", [])
            for label, text in _hook_sources(hook.get("command", ""))
            if _launches_unisolated_python(text)
        ]

        self.assertEqual(
            offenders,
            [],
            "hook(s) start a Python interpreter without -I -S, so a "
            "sitecustomize.py on a foreign PYTHONPATH would execute first: "
            f"{offenders}",
        )

    def test_warns_for_a_symlink_whose_basename_is_not_src(self) -> None:
        """Canonicalize before inspecting, as the router does.

        `/tmp/current-src -> /other-checkout/src` has basename `current-src`, so
        a name check on the RAW entry skips it. The router resolves first and
        strips that entry, so a raw check here leaves the layers disagreeing:
        ./bin/* gets fixed while the user is never warned about the bare-python3
        hazard that remains.
        """
        with tempfile.TemporaryDirectory() as td:
            real = Path(td, "real")
            _make_fake_checkout(real)
            link = Path(td, "current-src")
            link.symlink_to(real / "src")

            proc = _run_hook(str(link))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotEqual(
                proc.stdout.strip(),
                "",
                "a symlinked foreign src/ produced no warning; the detector "
                "inspected the unresolved path",
            )
            self.assertIn(
                str((real / "src").resolve()),
                json.loads(proc.stdout)["systemMessage"],
            )

    def test_audit_matches_relative_interpreter_paths(self) -> None:
        """`./.venv/bin/python3 -c ...` must count as an invocation.

        An earlier pattern only accepted an ABSOLUTE interpreter directory, so
        the relative form this repo actually uses would have executed with a
        foreign PYTHONPATH while the audit reported no offenders.
        """
        unisolated = [
            'python3 -c "x"',
            "/usr/bin/python3 -c 'x'",
            "env python3 -c 'x'",
            "./.venv/bin/python3 -c 'x'",
            ".venv/bin/python -m foo",
            "../other/bin/python3 script.py",
            "python3.11 -m unittest",
        ]
        for cmd in unisolated:
            with self.subTest(cmd=cmd):
                self.assertTrue(
                    _launches_unisolated_python(cmd),
                    f"missed an unisolated interpreter: {cmd}",
                )

        isolated_or_prose = [
            'python3 -I -S -c "x"',
            "./.venv/bin/python3 -I -S -c 'x'",
            "env python3 -I -S -m foo",
            '# python3 -c "in a comment"',
            'echo "run python3 -c to check"',
            "bash script.sh",
        ]
        for cmd in isolated_or_prose:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    _launches_unisolated_python(cmd),
                    f"false positive on: {cmd}",
                )

    def test_the_advised_diagnostic_is_itself_safe(self) -> None:
        """The command the warning suggests must not run foreign code.

        The warning fires precisely WHILE a foreign PYTHONPATH is active, so
        advising `python3 -c "import resume; print(resume.__file__)"` tells the
        reader to run the exact hazard being reported: the interpreter imports
        sitecustomize from the foreign entry at startup, then executes that
        checkout's package __init__ on import. Two separate payloads, before it
        prints anything.

        This runs the advised command verbatim, as a user copying it would, and
        asserts it stays silent while still naming the foreign path — a
        diagnostic that is safe but wrong would be no better.
        """
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))
            (foreign / "sitecustomize.py").write_text(
                'import sys; sys.stderr.write("PWNED_STARTUP\\n")\n'
            )
            pkg = foreign / "resume"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(
                'import sys; sys.stderr.write("PWNED_IMPORT\\n")\n'
            )

            message = json.loads(_run_hook(str(foreign)).stdout)["systemMessage"]
            advised = next(
                (ln.strip() for ln in message.splitlines() if "find_spec" in ln),
                "",
            )
            self.assertTrue(advised, f"no diagnostic found in:\n{message}")
            # The unsafe form may appear as a named counter-example ("that is
            # deliberately NOT ..."), so assert on the ADVISED line rather than
            # on the whole message — an earlier version of this check could not
            # tell "advises this" from "warns against this".
            self.assertNotIn(
                "import resume",
                advised,
                "the advised diagnostic imports the module, which executes "
                "code from whichever checkout wins",
            )

            # Tokenize and compare against a PINNED expectation before running.
            # `advised` comes from a tracked, branch-controlled file, so this
            # test executes whatever that line says. `shell=True` made it a
            # code-execution sink outright (an injected `touch` fired while the
            # test still reported OK), but dropping to shell=False only closed
            # the metacharacter route: `-I -S` is an import-isolation flag pair,
            # not a sandbox. A PR could rewrite the line to a perfectly valid
            #   python3 -I -S -c 'import os; os.system("...")'
            # which satisfies every shape check — right argv[0], -I, -S, -c, one
            # payload — and CI would run it.
            #
            # So the payload itself is pinned, not just the shape. Any edit to
            # the hook's advised line fails this assertion instead of executing,
            # and updating EXPECTED_DIAGNOSTIC_ARGV below is a deliberate act a
            # reviewer can see in the diff.
            argv = shlex.split(advised)
            self.assertTrue(advised, f"advised line did not tokenize: {advised!r}")
            self.assertEqual(
                argv,
                EXPECTED_DIAGNOSTIC_ARGV,
                "the hook's advised diagnostic changed.\n"
                "This test EXECUTES that line, so it is pinned rather than\n"
                "trusted. Review the new command — confirm it neither imports\n"
                "the module under test nor runs anything else — then update\n"
                "EXPECTED_DIAGNOSTIC_ARGV in this file to match.\n"
                f"  expected: {EXPECTED_DIAGNOSTIC_ARGV!r}\n"
                f"  actual:   {argv!r}",
            )

            proc = subprocess.run(  # nosec B603 - argv pinned above, no shell
                argv,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(foreign)},
                timeout=60,
            )
            combined = proc.stdout + proc.stderr
            self.assertNotIn("PWNED_STARTUP", combined)
            self.assertNotIn("PWNED_IMPORT", combined)
            # Safe is not enough — it must still give the right answer.
            self.assertIn(str(foreign / "resume"), proc.stdout)

    def test_a_tampered_advised_line_is_rejected_not_executed(self) -> None:
        """A rewritten advised line must fail the pin, not run.

        This is the gap that shape-only validation left open. The payload below
        is a *valid* `python3 -I -S -c <one string>` invocation: correct argv[0],
        both isolation flags present, exactly one argument after -c. Every check
        the shape-based version made would pass it, and it would then be handed
        to subprocess.run and executed.

        `-I -S` governs where imports come from; it does nothing to stop the
        payload calling out. So the guard has to be the pinned argv, and this
        test exists to prove that pin actually rejects a plausible tamper rather
        than merely being present.
        """
        tampered = (
            "python3 -I -S -c 'import os; os.system(\"echo PWNED_TAMPER\")'"
        )
        argv = shlex.split(tampered)

        # The tamper clears every shape check the previous version relied on,
        # which is exactly why those checks were not sufficient on their own.
        self.assertRegex(argv[0], r"(^|/)python(3(\.\d+)?)?$")
        self.assertIn("-I", argv)
        self.assertIn("-S", argv)
        self.assertIn("-c", argv)
        self.assertEqual(len(argv) - argv.index("-c"), 2)

        # The pin is what catches it. Compared, never executed.
        self.assertNotEqual(
            argv,
            EXPECTED_DIAGNOSTIC_ARGV,
            "a tampered diagnostic matched the pinned argv",
        )

    def test_a_checkout_path_ending_in_a_newline_is_still_detected(self) -> None:
        """A trailing newline in the checkout path must not hide the warning.

        Command substitution strips ALL trailing newlines, so the plain
        `resolved=$(cd "$entry" && pwd -P)` truncated such a path before the
        basename check ran: `.../weird\\n/src` came back as `.../weird/src`
        only by luck of the basename still being `src`, while a checkout dir
        itself ending in a newline lost the character entirely and the marker
        lookup then read the wrong pyproject.toml path.

        bin/_pathrepair.py handles this correctly via pathlib, so without the
        sentinel the shell and Python layers disagree about the same
        PYTHONPATH: the import is repaired for ./bin/* while the user is never
        warned about their bare-python3 hazard.
        """
        with tempfile.TemporaryDirectory() as td:
            # A directory whose name genuinely ends in a newline. POSIX allows
            # any byte but NUL and '/' in a path component.
            odd = Path(td, "checkout\n")
            foreign = _make_fake_checkout(odd)

            result = _run_hook(str(foreign))

            self.assertEqual(result.returncode, 0)
            self.assertTrue(
                result.stdout.strip(),
                "hook stayed silent about a foreign checkout whose path ends "
                "in a newline — the trailing-newline strip hid it",
            )
            message = json.loads(result.stdout)["systemMessage"]
            self.assertIn(
                "another checkout",
                message,
                f"expected the foreign-checkout warning, got: {message!r}",
            )

    def test_own_src_ending_in_a_newline_is_not_reported_as_foreign(self) -> None:
        """The `pwd -P` sentinel: own_src must survive the newline intact.

        This is the one truncation site the sibling newline test cannot reach.
        There the newline sits in a PARENT component (`checkout\\n/src`), so the
        split and the basename/dirname expansions are what mattered and
        `pwd -P` was never handed a path whose FINAL component ends in a
        newline.

        Here it is. `own_src` is resolved with `pwd -P` from $cwd_root/src, and
        each entry the same way; if only one of them is sentinel-guarded the two
        strings stop matching and the hook reports OUR OWN src/ as a foreign
        checkout — a false warning on every single session start.

        Modelled by pointing the hook at a checkout whose physical path ends in
        a newline and passing that same src/ as PYTHONPATH. Correct behaviour is
        silence: it is us, not another tree.
        """
        with tempfile.TemporaryDirectory() as td:
            # Final component ends in a newline — what `pwd -P` must preserve.
            odd_root = Path(td, "checkout\n")
            (odd_root / "src").mkdir(parents=True)
            (odd_root / "pyproject.toml").write_text(
                '[project]\nname = "personal-assistants"\nversion = "0.1.0"\n'
            )
            # A git repo, so `git rev-parse --show-toplevel` names this tree and
            # the hook treats it as the current checkout rather than bailing.
            subprocess.run(  # nosec B603 B607 - fixed argv, temp dir
                ["git", "init", "-q"],
                cwd=str(odd_root),
                capture_output=True,
                timeout=30,
                check=False,
            )

            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            env["PYTHONPATH"] = str(odd_root / "src")
            result = subprocess.run(  # nosec B603 B607 - in-repo script
                ["bash", str(HOOK)],
                capture_output=True,
                text=True,
                cwd=str(odd_root),
                env=env,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                result.stdout.strip(),
                "",
                "the hook warned about our OWN src/ — own_src and the resolved "
                "entry disagree because one of them lost its trailing newline",
            )

    def test_control_characters_in_a_path_still_emit_valid_json(self) -> None:
        """A tab or CR in a checkout path must not break the JSON contract.

        RFC 8259 §7 forbids raw U+0000–U+001F inside a JSON string. The escaper
        originally handled backslash, double-quote and newline only, so a
        directory legally named with a tab produced an unparseable object — the
        hook breaking its own one-object contract on exactly the kind of path it
        exists to report.

        Each name here is a real directory created on disk, so this asserts a
        reachable path rather than the escaper in isolation.
        """
        for label, name in (
            ("tab", "we\tird"),
            ("carriage-return", "we\rird"),
            ("double-quote", 'we"ird'),
            ("backslash", "we\\ird"),
        ):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as td:
                    foreign = _make_fake_checkout(Path(td, name))

                    proc = _run_hook(str(foreign))

                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertNotEqual(
                        proc.stdout.strip(), "", f"{label}: no warning emitted"
                    )
                    payload = json.loads(proc.stdout)  # raises if malformed
                    self.assertIn("systemMessage", payload)

    def test_output_is_a_single_json_object(self) -> None:
        """The hook contract is one JSON object on stdout — not prose."""
        with tempfile.TemporaryDirectory() as td:
            foreign = _make_fake_checkout(Path(td, "other-checkout"))

            proc = _run_hook(str(foreign))

            # json.loads on the whole stream: extra lines or a bare string fail.
            payload = json.loads(proc.stdout)
            self.assertIsInstance(payload, dict)
            self.assertEqual(list(payload.keys()), ["systemMessage"])


if __name__ == "__main__":
    unittest.main()
