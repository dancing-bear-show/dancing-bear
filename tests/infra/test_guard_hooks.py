"""Run the .claude/hooks shell suites under unittest discovery.

WHY THIS WRAPPER EXISTS
-----------------------
The guard-hook suites are shell scripts. They were documented as manual commands
only, so `make test` and CI -- both of which run Python unittest discovery and
nothing else -- never invoked them. A regression in a hook that blocks credential
reads would therefore ship green, which is the one class of regression these
hooks exist to prevent.

Shelling out from a discovered test is the smallest change that fixes that: no new
Makefile target to remember, no second CI step to keep in sync with the first, and
the suites stay runnable by hand exactly as the README documents. `make test`,
`make cov`, and `.github/workflows/ci.yml` all pick this up automatically because
all three go through discovery.

The suites are self-contained bash and require only `jq`. When `jq` or `bash` is
missing the test FAILS.

WHY FAIL RATHER THAN SKIP
-------------------------
This used to call ``skipTest``, on the reasoning that a missing tool is an unknown
result rather than a passing one. That reasoning is right about the result and wrong
about the consequence: unittest reports a skipped test as a green run, CI goes green,
and nobody reads the skip line. A runner without ``jq`` would therefore report success
having exercised not one guard -- the precise fail-open shape that both hooks and the
``_harness.sh`` classifier were rewritten to eliminate, reproduced one level up in the
thing that runs them.

A tool these tests require is a dependency, not an environmental accident. ``jq`` is
installed explicitly in ``.github/workflows/ci.yml`` so that failing here is safe:
if it ever goes missing, the correct signal is a red build naming the missing tool,
not a silent pass.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404 - runs trusted in-repo shell suites
import unittest
from pathlib import Path

from tests.fixtures import repo_root

HOOKS_DIR = repo_root() / ".claude" / "hooks"
TESTS_DIR = HOOKS_DIR / "tests"

# Each suite exits 0 on all-pass and 1 on any failure, and prints one line per case.
SUITES = (
    "block-destructive-bash.test.sh",
    "block-protected-paths.test.sh",
    "block-readonly-role-writes.test.sh",
    # Derived from guard-contract.yaml rather than from past bugs. Kept alongside
    # the regression suite above, not instead of it: the two catch different things,
    # and a probe reproducing PR #395's round-8 traversal bypass failed the contract
    # while the 301-case regression suite passed it clean.
    "guard-contract.test.sh",
    "statusline.test.sh",
)

# The summary line every suite ends with, e.g. "statusline: 76 passed, 0 failed, 76 total".
# Parsed rather than merely searched for "ALL PASS" -- see _assert_ran_cases below.
_SUMMARY_RE = re.compile(
    r"^\S+: (?P<passed>\d+) passed, (?P<failed>\d+) failed, (?P<total>\d+) total$",
    re.MULTILINE,
)


def _contract_root_dirs() -> frozenset[str]:
    """Top-level repo names guard-contract.test.sh may create for its setup.

    Derived from guard-contract.yaml rather than typed out: a hand-listed set goes
    stale the moment a row adds a new artifact root. Covers both ``needs_dirs``
    and the first path segment of every ``{REPO}/...`` link in ``needs_links``,
    whose parent directory ``mkdir -p`` creates.
    """
    import yaml  # lazy: PyYAML is a dev dependency, as it is for the suite itself

    doc = yaml.safe_load((TESTS_DIR / "guard-contract.yaml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for group in doc.get("promises", []):
        names.update(group.get("needs_dirs") or [])
        for item in group.get("needs_links") or []:
            link = item["link"]
            if link.startswith("{REPO}/"):
                names.add(link.removeprefix("{REPO}/").split("/", 1)[0])
    return frozenset(names)


def _untracked() -> set[str]:
    """Untracked paths in the checkout, one entry per FILE (not per directory)."""
    out = subprocess.run(  # nosec B603 B607 - fixed git argv, no user input
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_root()),
    ).stdout
    return {line[3:] for line in out.splitlines() if line.startswith("?? ")}


def _missing_tool() -> str | None:
    """Return the name of the first required tool that is not on PATH."""
    for tool in ("bash", "jq"):
        if shutil.which(tool) is None:
            return tool
    return None


class TestGuardHookSuites(unittest.TestCase):
    """Each .claude/hooks shell suite must exit 0.

    SUITES is the single source of truth, and BOTH halves of the invariant are
    driven from it:

    * ``test_suites_on_disk_match_the_tuple`` compares the tuple against the
      directory, so a suite present on disk but missing from the tuple fails.
    * ``_attach`` generates one ``test_*`` method per tuple entry, so a suite
      listed in the tuple always runs.

    Neither half alone is sufficient, and the second is the one that is easy to
    lose: an earlier version of this file hand-wrote the per-suite methods, which
    let a name sit in SUITES with no method to execute it -- listed, checked
    against disk, and silently never run. Any future edit here must keep the
    method list derived from SUITES rather than typed out.
    """

    def _run_suite(self, name: str) -> None:
        missing = _missing_tool()
        self.assertIsNone(
            missing,
            msg=(
                f"{missing} is not on PATH, so the guard-hook suites cannot run. "
                "This is a failure, not a skip: a skipped run reports green while "
                "exercising none of the guards, which is exactly the fail-open "
                "behaviour these hooks exist to prevent. Install it "
                "(macOS: brew install jq) -- CI installs it in ci.yml."
            ),
        )

        suite: Path = TESTS_DIR / name
        self.assertTrue(suite.is_file(), f"missing hook suite: {suite}")

        root = repo_root()
        untracked_before = _untracked()
        root_dirs = _contract_root_dirs()
        absent_before = {d for d in root_dirs if not os.path.lexists(root / d)}

        # encoding/errors are pinned rather than left to the locale. statusline.sh
        # emits box-drawing and middle-dot characters, and text=True alone decodes
        # with the locale's preferred encoding -- ASCII on a CI runner with no
        # LANG set, which raises UnicodeDecodeError on the first '·' and turns a
        # passing suite into an error. errors="replace" keeps a decoding problem
        # from masking the assertion the test actually makes.
        # B607: "bash" is resolved from PATH deliberately. /bin/bash does not exist
        # on NixOS, and the Linux CI runner and macOS dev machines put it in
        # different places. Anyone who can alter PATH for this process can already
        # edit the test file, so the partial path adds no new exposure. The nosec
        # must stay on the flagged line below -- bandit ignores it on a preceding
        # comment line, exactly like NOSONAR.
        proc = subprocess.run(  # nosec B603 B607 - trusted in-repo script, no user input
            ["bash", str(suite)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(repo_root()),
            timeout=180,
        )
        # The suite's own output is the useful failure message: it names every case
        # that failed and what it expected. Reproducing that in assert messages would
        # duplicate it and then drift.
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"\n--- {name} ---\n{proc.stdout}\n{proc.stderr}",
        )
        # "ALL PASS" is necessary but NOT sufficient -- see _assert_ran_cases, which
        # checks that cases actually ran and that all of them passed.
        self.assertIn("ALL PASS", proc.stdout, msg=proc.stdout)
        self._assert_ran_cases(name, proc.stdout)
        self._assert_left_nothing(name, untracked_before, absent_before)

    def _assert_left_nothing(
        self, name: str, untracked_before: set[str], absent_before: set[str]
    ) -> None:
        """A suite must not leave files or directories behind in the checkout.

        Both halves are needed. The untracked snapshot catches a leftover file or
        symlink. It cannot catch the bug that motivated this check: guard-contract
        left eight EMPTY directories at the repo root (``analysis/``, ``out/``,
        ...), and ``git status`` never reports an empty directory -- so an
        untracked-only assertion passes on exactly that bug. Hence the second
        half, which checks by name that every setup directory that was absent
        before the run is absent after it.
        """
        root = repo_root()
        self.assertEqual(
            _untracked() - untracked_before,
            set(),
            msg=f"{name} left untracked files in the checkout",
        )
        leftover = sorted(d for d in absent_before if os.path.lexists(root / d))
        self.assertEqual(
            leftover,
            [],
            msg=f"{name} left setup directories at the repo root: {leftover}",
        )

    def test_contract_root_dirs_are_derived(self) -> None:
        """The leftover check knows the names it must look for.

        An empty derivation -- a renamed YAML key, a moved file -- would make the
        by-name half of ``_assert_left_nothing`` vacuous while it stayed green.
        """
        self.assertLessEqual(
            {"analysis", "out", "workspace", "outputs"}, _contract_root_dirs()
        )

    def _assert_ran_cases(self, name: str, stdout: str) -> None:
        """A suite that ran zero cases has not tested anything.

        ``ALL PASS`` alone is not evidence of a passing run. ``_summary`` prints it
        whenever no case FAILED, and a suite whose cases were all deleted -- or that
        exited before reaching them -- fails nothing. Both counters sit at zero, the
        exit code is 0, and every layer above reports green having exercised not one
        guard. ``_harness.sh`` now refuses that case at the source; this asserts the
        same thing here so the wrapper cannot be satisfied by a suite that silently
        stopped running cases.
        """
        match = _SUMMARY_RE.search(stdout)
        if match is None:
            self.fail(f"{name} printed no parsable summary line:\n{stdout}")
        passed = int(match.group("passed"))
        failed = int(match.group("failed"))
        total = int(match.group("total"))
        self.assertGreater(
            total,
            0,
            msg=f"{name} ran zero cases -- an empty suite is not a passing suite",
        )
        self.assertEqual(
            passed,
            total,
            msg=f"{name} reported {failed} failure(s) of {total}:\n{stdout}",
        )

    def test_suites_on_disk_match_the_tuple(self) -> None:
        """Every *.test.sh on disk is in SUITES, and vice versa.

        This is only half the invariant. The other half -- that every entry in
        SUITES actually RUNS -- is enforced by ``_attach`` below, which generates
        one test method per entry. See this class's docstring for why the two
        halves must both be driven from SUITES.
        """
        on_disk = {p.name for p in TESTS_DIR.glob("*.test.sh")}
        self.assertEqual(
            on_disk,
            set(SUITES),
            msg="hook suites on disk do not match the SUITES tuple in this file",
        )
        # Guards the guard: an emptied SUITES would make the assertEqual above pass
        # against an emptied directory and run nothing at all.
        self.assertTrue(SUITES, msg="SUITES is empty -- no hook suite would run")


class TestGuardHooksAreWired(unittest.TestCase):
    """The guards must be WIRED, not merely present and passing their suites.

    Everything else in this file exercises the hook scripts by piping payloads at
    them directly. That proves each SCRIPT works. It says nothing about whether
    the harness ever invokes them -- and the two are independent.

    That gap was not hypothetical. ``block-destructive-bash.sh`` and
    ``block-protected-paths.sh`` shipped with suites, a README, and **no
    ``PreToolUse`` entry in any settings file**. Every protection in them was
    dormant, while this suite reported green, because a passing script test and a
    live hook are different claims. Deleting the settings block today would
    reproduce exactly that state: all hook cases green, all guards off.

    So these tests assert the wiring itself.
    """

    SETTINGS = repo_root() / ".claude" / "settings.json"

    # Test-only seam. The executing test below has to be provable -- the way to
    # show it can tell an enforcing hook from a swallowed one is to point it at a
    # settings file with `|| true` appended and watch it go red. Editing the real
    # .claude/settings.json to do that is not an option: a guard hook blocks
    # writes to it, and a probe that mutates the file it is validating can leave
    # the repo in the broken state if it dies mid-run. So the path is overridable
    # for a probe, and the override is deliberately NOT read from anywhere in the
    # normal path -- unset, every test reads the real file.
    SETTINGS_ENV_OVERRIDE = "DANCING_BEAR_GUARD_SETTINGS"

    # Every hook script that must be reachable from a PreToolUse entry, with the
    # tools its matcher has to cover. Keyed by script name so a renamed script
    # fails here rather than silently dropping its coverage.
    REQUIRED_HOOKS = {
        "block-destructive-bash.sh": {"Bash"},
        "block-protected-paths.sh": {"Write", "Edit"},
        "block-readonly-role-writes.sh": {"Write", "Edit", "Bash"},
    }

    def _settings_path(self) -> Path:
        override = os.environ.get(self.SETTINGS_ENV_OVERRIDE)
        return Path(override) if override else self.SETTINGS

    def _pre_tool_use(self) -> list[dict]:
        settings = self._settings_path()
        self.assertTrue(settings.is_file(), f"missing {settings}")
        data = json.loads(settings.read_text(encoding="utf-8"))
        hooks = data.get("hooks", {})
        entries = hooks.get("PreToolUse")
        self.assertIsInstance(
            entries,
            list,
            msg=(
                "no PreToolUse block in .claude/settings.json -- the guard hooks are "
                "dormant. Their own suites will still pass; that is the point of this "
                "test."
            ),
        )
        return entries

    # A command counts as invoking a guard only if it runs THAT script: `bash` (or a
    # path ending in it) followed by a path whose basename is the script, optionally
    # quoted, with $CLAUDE_PROJECT_DIR or another prefix in front.
    #
    # A substring test is what this replaced, and it was too weak in three separate
    # ways -- all three demonstrated against the real settings file rather than
    # reasoned about. It accepted a hook whose `type` was not "command", a command
    # that merely MENTIONED the filename while running `echo`, and a command pointing
    # at a copy of the script somewhere else entirely. Each of those is a dormant
    # guard reported as active, which is the exact failure this class exists to catch.
    # Shell operators that end one command and begin another, so the token after
    # them is a command word again rather than an argument.
    _SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "{", "}"})

    def _invocations(self, command: str) -> list[tuple[str, str]]:
        """Return (interpreter, operand) pairs where the operand is being RUN.

        Tokenised with ``shlex`` rather than matched with a regex, because the
        question -- "is this token a command word or an argument?" -- is
        structural, and a regex cannot answer it. The previous version matched
        ``bash`` anywhere after whitespace, so ``echo bash <path>`` counted as an
        invocation even though it only prints the path. Demonstrated against the
        real settings file, along with a commented-out command and a path
        mentioned inside an echo string; all three reported a dormant guard as
        wired.

        Position is what decides it: a token is a command word only at the start
        of the command or immediately after a separator. ``bash`` sitting in
        argument position is an argument.
        """
        try:
            tokens = shlex.split(command, comments=True)
        except ValueError:
            # Unbalanced quotes -- treat as running nothing rather than guessing.
            return []

        pairs: list[tuple[str, str]] = []
        for index in self._command_word_positions(tokens):
            token = tokens[index]
            if Path(token).name not in {"bash", "sh", "zsh"}:
                continue
            operand = self._first_operand(tokens[index + 1:])
            if operand is not None:
                pairs.append((token, operand))
        return pairs

    def _command_word_positions(self, tokens: list[str]) -> list[int]:
        """Indices of tokens in command position (start, or after a separator)."""
        positions: list[int] = []
        at_command_position = True
        for index, token in enumerate(tokens):
            if token in self._SEPARATORS:
                at_command_position = True
                continue
            if at_command_position:
                # Env-var assignments (FOO=bar cmd) keep the NEXT token in
                # command position rather than consuming it.
                if "=" in token and not token.startswith("="):
                    continue
                positions.append(index)
            at_command_position = False
        return positions

    def _first_operand(self, rest: list[str]) -> str | None:
        """First non-flag token before the next separator, or None."""
        for token in rest:
            if token in self._SEPARATORS:
                return None
            if token.startswith("-"):
                continue
            return token
        return None

    def _invoked_scripts(self, hook: dict) -> set[str]:
        """Return the guard scripts a hook actually invokes, or an empty set.

        Empty for a non-command hook, for a command that does not run a script at
        all, for one that only mentions a script's path, and for one that runs a
        script from outside this repo's hooks dir.
        """
        if hook.get("type") != "command":
            return set()
        command = hook.get("command", "")
        if not isinstance(command, str):
            return set()
        found: set[str] = set()
        for _interpreter, operand in self._invocations(command):
            script = Path(operand).name
            if script not in self.REQUIRED_HOOKS:
                continue
            # The invoked path must resolve to the repo's own hooks directory. A
            # command running a same-named script from elsewhere leaves this guard
            # dormant while looking wired.
            expanded = operand.replace("$CLAUDE_PROJECT_DIR", str(repo_root()))
            expanded = expanded.replace("${CLAUDE_PROJECT_DIR}", str(repo_root()))
            parent = Path(expanded).parent
            if str(parent) in {"", "."}:
                continue
            if parent.resolve() != HOOKS_DIR.resolve():
                continue
            found.add(script)
        return found

    def test_every_guard_script_is_wired(self) -> None:
        """Each guard is actually INVOKED by a command hook, not merely named."""
        entries = self._pre_tool_use()
        wired = {
            script
            for entry in entries
            for hook in entry.get("hooks", [])
            for script in self._invoked_scripts(hook)
        }
        missing = set(self.REQUIRED_HOOKS) - wired
        self.assertEqual(
            missing,
            set(),
            msg=(
                f"these guard scripts are not invoked by any PreToolUse command hook: "
                f"{sorted(missing)}. Naming a script in a non-command hook, in a "
                f"command that runs something else, or at a path outside "
                f"{HOOKS_DIR} all leave the guard dormant."
            ),
        )

    def test_each_matcher_covers_the_tools_its_guard_needs(self) -> None:
        """A wired hook whose matcher omits a tool is half-dormant.

        ``block-readonly-role-writes.sh`` was wired as ``Write`` only while its
        Bash branch existed, so `echo x > src/mail/cli.py` walked straight past a
        guard that was, by the previous test's standard, correctly wired.
        """
        entries = self._pre_tool_use()
        # Accumulate per script: a guard may legitimately be wired by more than one
        # entry, and it is covered if the union of those matchers covers its tools.
        covered: dict[str, set[str]] = {s: set() for s in self.REQUIRED_HOOKS}
        for entry in entries:
            matcher = entry.get("matcher", "")
            tools = set(matcher.split("|")) if matcher else set()
            for hook in entry.get("hooks", []):
                for script in self._invoked_scripts(hook):
                    covered[script] |= tools

        for script, needed in self.REQUIRED_HOOKS.items():
            if not covered[script]:
                continue  # not wired at all -- the other test reports that
            self.assertLessEqual(
                needed,
                covered[script],
                msg=(
                    f"{script} is wired with matcher coverage "
                    f"{sorted(covered[script])}, which does not cover "
                    f"{sorted(needed - covered[script])}. The guard would be "
                    f"silently inactive for those tools."
                ),
            )

    def test_wired_commands_point_at_files_that_exist(self) -> None:
        """A wired path that does not resolve is a guard that cannot run."""
        entries = self._pre_tool_use()
        for entry in entries:
            for hook in entry.get("hooks", []):
                for script in self._invoked_scripts(hook):
                    self.assertTrue(
                        (HOOKS_DIR / script).is_file(),
                        msg=f"{script} is wired but missing from {HOOKS_DIR}",
                    )

    # A payload each guard must BLOCK, i.e. must make the configured command exit 2.
    #
    # Every one of these was verified by piping it at the hook directly before being
    # written down -- none is inferred from reading the script. They are also the
    # shapes the hooks' own suites use, so a hook change that invalidates a payload
    # fails that suite too rather than silently turning this test into a no-op.
    #
    # `{repo_root}` is substituted at call time. block-readonly-role-writes.sh judges
    # a relative file_path against the payload's own `cwd`, so the field is load-
    # bearing: without it the path is unresolvable and the hook may not block.
    _BLOCKING_PAYLOADS = {
        "block-destructive-bash.sh": {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        },
        "block-protected-paths.sh": {
            "tool_name": "Write",
            "tool_input": {"file_path": "{home}/.ssh/id_rsa", "content": "x"},
        },
        "block-readonly-role-writes.sh": {
            "agent_type": "researcher",
            "cwd": "{repo_root}",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/mail/cli.py", "content": "x"},
        },
    }

    @staticmethod
    def _substitute(value: object, repo: str, home: str) -> object:
        """Fill {repo_root}/{home} placeholders through a nested payload."""
        if isinstance(value, str):
            return value.format(repo_root=repo, home=home)
        if isinstance(value, dict):
            return {
                k: TestGuardHooksAreWired._substitute(v, repo, home)
                for k, v in value.items()
            }
        return value

    def test_wired_commands_actually_block(self) -> None:
        """Run each configured command for real and assert it exits 2.

        WHY EXECUTION AND NOT ANOTHER PARSE
        -----------------------------------
        Every other test in this class inspects the settings TEXT. That proves a
        command naming a guard is configured; it proves nothing about whether the
        guard's decision survives to the harness. Claude reads exit status 2 as
        "blocked", and a status-swallowing wrapper erases it without touching the
        command's text at all::

            bash "$CLAUDE_PROJECT_DIR/.claude/hooks/block-readonly-role-writes.sh" || true

        That command passes every textual check above -- correct interpreter,
        correct operand, resolving inside the repo's hooks dir, matcher intact --
        and exits 0 on a payload the hook blocked. The guard is dormant and the
        wiring suite is green, which is precisely the state this whole class was
        written after discovering. Measured, not reasoned about: piping the
        researcher payload through that wrapper exits 0 while the bare hook exits
        2.

        A blacklist of swallowing constructs would be the wrong fix -- `|| true`,
        `; true`, `| cat`, `set +e`, a wrapper script, and `exit 0` at the end of a
        multi-command hook all have the same effect and no finite pattern list
        catches them. Running the command is the only check that covers the class
        rather than the instances.

        SCOPE: every guard in REQUIRED_HOOKS has a verified blocking payload, so
        all three are executed. A future guard added without one would be caught
        by the assertion below rather than silently skipped.
        """
        missing = shutil.which("bash") is None or shutil.which("jq") is None
        self.assertFalse(
            missing,
            msg="bash and jq are required to execute the configured hook commands",
        )

        repo = str(repo_root())
        home = str(Path.home())
        executed: set[str] = set()

        for entry in self._pre_tool_use():
            for hook in entry.get("hooks", []):
                for script in self._invoked_scripts(hook):
                    payload = self._BLOCKING_PAYLOADS.get(script)
                    self.assertIsNotNone(
                        payload,
                        msg=(
                            f"{script} is wired but has no verified blocking payload "
                            f"in _BLOCKING_PAYLOADS, so its exit status is never "
                            f"checked. Add one -- and verify it blocks by piping it "
                            f"at the hook -- rather than leaving the guard unproven."
                        ),
                    )
                    self._assert_command_blocks(
                        script,
                        hook["command"],
                        json.dumps(self._substitute(payload, repo, home)),
                        repo,
                    )
                    executed.add(script)

        # Guards the guard: an empty settings block, or _invoked_scripts returning
        # nothing, would satisfy the loop above by never entering it.
        self.assertEqual(
            executed,
            set(self.REQUIRED_HOOKS),
            msg=(
                f"only {sorted(executed)} were executed; "
                f"{sorted(set(self.REQUIRED_HOOKS) - executed)} never ran, so their "
                f"exit status is unproven"
            ),
        )

    def _assert_command_blocks(
        self, script: str, command: str, payload: str, repo: str
    ) -> None:
        """Run the command string AS CONFIGURED and require exit 2.

        Run through the shell rather than tokenised and exec'd, because the point
        is to exercise the command exactly as the harness would -- including any
        `|| true`, pipeline, or subshell that a tokenised re-execution would
        discard along with the bug it hides.
        """
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = repo
        # B602: the command comes from this repo's own settings.json, which is the
        # artifact under test. Running it through the shell is the whole point --
        # see the docstring. No external input reaches it.
        proc = subprocess.run(  # nosec B602 - in-repo settings command, executed deliberately
            command,
            shell=True,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=repo,
            env=env,
            timeout=60,
        )
        self.assertEqual(
            proc.returncode,
            2,
            msg=(
                f"the configured command for {script} exited {proc.returncode} on a "
                f"payload the hook blocks when run directly. Exit 2 is how a block "
                f"reaches Claude; any other status leaves the guard dormant while "
                f"the textual wiring tests stay green.\n"
                f"  command: {command}\n"
                f"  payload: {payload}\n"
                f"  stdout:  {proc.stdout}\n"
                f"  stderr:  {proc.stderr}"
            ),
        )


def _attach(name: str) -> None:
    """Generate one test method per SUITES entry, so each is schedulable alone.

    The generation is what keeps the split safe. Hand-writing one method per
    suite is what this file did BEFORE the methods were consolidated, and it had
    a real gap: the tuple was checked against disk but never iterated, so a name
    added to SUITES with no matching ``test_*`` method satisfied the equality
    check and silently never ran. The tuple looked like the source of truth while
    the hand-maintained method list actually was one.

    Deriving the methods FROM SUITES at import time restores the three-state
    invariant the consolidated method provided -- absent from the tuple (the
    directory check fails), present and passing, or present and failing -- with
    no fourth state where a suite is listed and quietly skipped. A name cannot be
    in SUITES without getting a method here, because the method list IS SUITES.

    Why methods rather than the previous ``subTest`` loop: subTest reports each
    case separately but still runs them inside ONE test method, which is a unit
    of scheduling. Test-level parallel runners distribute methods, so the loop
    was a hard serial floor -- ~77s of a ~93s suite. Separate methods let the
    suites run concurrently without changing what any of them assert.

    This mirrors ``tests/core_tests/test_capsule_parser_drift.py``, which
    generates its per-app methods the same way. Plain ``setattr`` over a
    module-level loop needs no metaclass and no new dependency; the repo runs
    stdlib unittest.
    """

    def test(self, _name: str = name) -> None:
        self._run_suite(_name)

    # "block-destructive-bash.test.sh" -> "test_block_destructive_bash_suite_passes"
    stem = name.removesuffix(".test.sh").replace("-", "_")
    test.__name__ = f"test_{stem}_suite_passes"
    test.__doc__ = f"{name} exits 0 with every case passing."
    setattr(TestGuardHookSuites, test.__name__, test)


for _suite in SUITES:
    _attach(_suite)


if __name__ == "__main__":
    unittest.main()
