"""Tests for the tmux session-namer hook and the matcher its installer uses.

Why these exist: the hook-matching logic in `.claude/skills/install-tmux-namer/
SKILL.md` has been wrong three times, each time caught by a reviewer rather than
by CI, and each fix traded one class of false result for another.

    v1  `'tmux-session-namer' in cmd`        matched an unrelated ...-custom.py
    v2  token in (HOOK_PATH, expanduser())   missed $HOME and absolute spellings
    v3  basename(token) == basename(target)  matched /tmp/tmux-session-namer.py

The matcher decides whether the installer REWRITES an existing hook entry, so a
false positive destroys someone else's hook and a false negative leaves a stale
unisolated one wired while appending a duplicate. That is worth a table rather
than a patch per reported case.

The installer's Python lives inside a Markdown fence, so these tests extract it
from the file and exercise the real thing. Testing a retyped copy is how a
SyntaxError in that block once reached a shipped round: the probe validated the
transcription, not the file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "install-tmux-namer" / "SKILL.md"
HOOK = REPO_ROOT / "configs" / "llm" / "tmux-session-namer.py"

_HEREDOC = re.compile(r"python3 -I -S - << 'PY'\n(.*?)\nPY", re.S)
_INLINE = re.compile(r'python3 -I -S -c "\n(.*?)\n"', re.S)


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _settings_patch_source() -> str:
    match = _HEREDOC.search(_skill_text())
    if match is None:
        raise AssertionError("settings-patch heredoc not found in SKILL.md")
    return match.group(1)


def _inline_snippets() -> list[str]:
    return _INLINE.findall(_skill_text())


def _load_matcher(home: str):
    """Return the installer's `is_managed_hook`, with HOME faked per call.

    Executes only the matcher definition, not the whole patch script, so loading
    it has no side effects on the real settings.json.

    HOME must be set while the matcher RUNS, not merely while it is defined: it
    resolves `~` at call time. Setting it only around `exec` left the function
    resolving against the developer's real home, which made three correct
    assertions fail and briefly looked like a defect in the matcher.
    """
    source = _settings_patch_source()
    start = source.index("HOOK_PATH =")
    end = source.index("upgraded = False")
    namespace: dict[str, Any] = {}
    exec(compile("import os\n" + source[start:end], "<matcher>", "exec"), namespace)  # nosec B102 - repo-owned SKILL.md source under test
    matcher: Callable[[str], object] = namespace["is_managed_hook"]

    def with_fake_home(cmd: str) -> bool:
        original = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            return bool(matcher(cmd))
        finally:
            if original is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original

    return with_fake_home


class TestEmbeddedCodeIsValid(unittest.TestCase):
    """Every executable block in the skill must at least compile."""

    def test_settings_patch_compiles(self) -> None:
        compile(_settings_patch_source(), "<settings-patch>", "exec")

    def test_inline_snippets_compile(self) -> None:
        snippets = _inline_snippets()
        self.assertGreaterEqual(len(snippets), 1, "expected at least one inline -c snippet")
        for index, snippet in enumerate(snippets):
            with self.subTest(snippet=index):
                compile(snippet, f"<inline-{index}>", "exec")

    def test_hook_compiles(self) -> None:
        compile(HOOK.read_text(encoding="utf-8"), str(HOOK), "exec")


class TestHookMatcher(unittest.TestCase):
    """The matcher must identify our installed script and nothing else.

    Written from the requirement, not from the implementation: the table covers
    spellings that must match and same-named files elsewhere that must not.
    """

    HOME = "/Users/testuser"

    def setUp(self) -> None:
        self.is_managed = _load_matcher(self.HOME)
        self.ours = f"{self.HOME}/.claude/hooks/tmux-session-namer.py"

    # -- must match: our script, however the path is written -----------------

    def test_matches_tilde_form(self) -> None:
        cmd = "python3 -I -S ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"
        self.assertTrue(self.is_managed(cmd))

    def test_matches_absolute_form(self) -> None:
        self.assertTrue(self.is_managed(f"python3 -I -S {self.ours}"))

    def test_matches_home_variable_forms(self) -> None:
        for spelling in ("$HOME", "${HOME}"):
            with self.subTest(spelling=spelling):
                cmd = f"python3 -I -S {spelling}/.claude/hooks/tmux-session-namer.py"
                self.assertTrue(self.is_managed(cmd))

    def test_matches_non_normalised_paths(self) -> None:
        """Redundant separators and dot segments name the same file."""
        variants = [
            f"{self.HOME}//.claude//hooks//tmux-session-namer.py",
            f"{self.HOME}/.claude/hooks/./tmux-session-namer.py",
            f"{self.HOME}/.claude/hooks/../hooks/tmux-session-namer.py",
        ]
        for path in variants:
            with self.subTest(path=path):
                self.assertTrue(self.is_managed(f"python3 {path}"))

    def test_matches_legacy_unisolated_form(self) -> None:
        """The entry an earlier installer wrote, without -I -S.

        This one must match: failing to recognise it is what made a reinstall
        append a second hook instead of upgrading the first.
        """
        cmd = "python3 ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"
        self.assertTrue(self.is_managed(cmd))

    def test_matches_alternative_interpreters(self) -> None:
        for prefix in ("python3.11", "env python3", "/usr/bin/python3 -I -S"):
            with self.subTest(prefix=prefix):
                cmd = f"{prefix} ~/.claude/hooks/tmux-session-namer.py"
                self.assertTrue(self.is_managed(cmd))

    def test_matches_past_flags_that_consume_an_argument(self) -> None:
        """Some interpreter options take an operand of their own.

        Treating every `-...` token as argument-free makes the option's operand
        look like the script name, so a real invocation of ours goes unrecognised
        and the installer appends a SECOND hook beside it.
        """
        for flags in (
            "-W ignore",
            "-X faulthandler",
            "--check-hash-based-pycs default",
            "-I -S -W ignore",
        ):
            with self.subTest(flags=flags):
                cmd = f"python3 {flags} ~/.claude/hooks/tmux-session-namer.py"
                self.assertTrue(
                    self.is_managed(cmd),
                    f"missed a real invocation through {flags!r} — the installer "
                    "would append a duplicate hook",
                )

    def test_matches_our_own_canonical_wired_form(self) -> None:
        """The command the installer itself writes must always be recognised.

        It ends in `2>/dev/null || true`, so any rule that rejects chained
        commands outright would stop the installer recognising its own entry —
        and it would then append a duplicate on every single run.
        """
        canonical = (
            "python3 -I -S ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"
        )
        self.assertTrue(
            self.is_managed(canonical),
            "the installer no longer recognises the command it writes; it would "
            "append a duplicate hook on every run",
        )

    # -- must NOT match: a file we do not own --------------------------------

    def test_rejects_a_quoted_home_token(self) -> None:
        """A single-quoted `$HOME` or `~` reaches python LITERALLY.

        The shell does not expand either inside single quotes, so python is
        handed a path that does not exist and our hook never runs. `shlex.split`
        discards the quoting, and expanding afterwards makes an unrelated command
        look like ours — which this matcher would then rewrite.
        """
        for cmd in (
            "python3 '$HOME/.claude/hooks/tmux-session-namer.py'",
            "python3 '~/.claude/hooks/tmux-session-namer.py'",
            "python3 -I -S '${HOME}/.claude/hooks/tmux-session-namer.py'",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.is_managed(cmd),
                    "single-quoted tokens are literal to the shell, so this "
                    f"command does not run our hook: {cmd!r}",
                )

    def test_rejects_a_chain_that_would_lose_the_users_command(self) -> None:
        """Matching must not lead to deleting part of someone's command.

        The upgrade replaces the WHOLE command string. A chain carrying a user's
        own work after our invocation therefore loses it silently, so such a
        command must not be claimed — with the explicit exception of the
        canonical `2>/dev/null || true` form the installer writes itself, which
        is covered separately above.
        """
        ours = "~/.claude/hooks/tmux-session-namer.py"
        for cmd in (
            f"python3 -I -S {ours} && echo audit",
            f"python3 -I -S {ours} || logger 'namer failed'",
            f"python3 -I -S {ours}; /usr/local/bin/my-other-hook",
            f"python3 -I -S {ours} && notify-send done",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.is_managed(cmd),
                    "rewriting this would silently delete the user's chained "
                    f"command: {cmd!r}",
                )

    def test_rejects_the_path_as_another_options_operand(self) -> None:
        """`-c` takes code and `-m` takes a module name, not a script to run.

        A command that merely NAMES our path as one of those operands is not
        running it, and this matcher gates a rewrite — so claiming it would
        destroy someone else's command.
        """
        cases = [
            "python3 -c '~/.claude/hooks/tmux-session-namer.py'",
            'python3 -c "~/.claude/hooks/tmux-session-namer.py"',
            "python3 -m ~/.claude/hooks/tmux-session-namer.py",
            "python3 -W ~/.claude/hooks/tmux-session-namer.py",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                self.assertFalse(
                    self.is_managed(cmd),
                    f"would rewrite a command that only names the path: {cmd!r}",
                )

    def test_rejects_same_name_in_another_directory(self) -> None:
        """A basename comparison alone wrongly claims these."""
        for path in (
            "/tmp/tmux-session-namer.py",  # nosec B108 - test string only
            "~/dev/tmux-session-namer.py",
            "/opt/.claude/hooks/tmux-session-namer.py",
            f"{self.HOME}/Downloads/tmux-session-namer.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    self.is_managed(f"python3 {path}"),
                    f"would rewrite an unrelated hook at {path}",
                )

    def test_rejects_similar_names_in_our_directory(self) -> None:
        """A substring comparison wrongly claims these."""
        for name in (
            "tmux-session-namer-custom.py",
            "my-tmux-session-namer.py",
            "tmux-session-namer.py.bak",
            "other-hook.py",
        ):
            with self.subTest(name=name):
                cmd = f"python3 ~/.claude/hooks/{name}"
                self.assertFalse(self.is_managed(cmd), f"wrongly claimed {name}")

    def test_rejects_unrelated_commands(self) -> None:
        for cmd in ("echo hello", "tmux-session-namer", "python3 -c 'print(1)'", ""):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.is_managed(cmd))

    def test_rejects_relative_path(self) -> None:
        """Claude Code guarantees no working directory, so a bare relative path
        cannot be shown to be ours."""
        self.assertFalse(self.is_managed("python3 tmux-session-namer.py"))

    def test_rejects_a_users_own_fork_elsewhere(self) -> None:
        """Found by an external critique, not by this table's first draft.

        Someone running their own copy out of ~/bin must keep it. Rewriting it
        would replace their fork with ours and print "Upgraded".
        """
        for cmd in (
            "python3 ~/bin/tmux-session-namer.py --my-fork",
            "python3 $HOME/bin/tmux-session-namer.py",
            "cat ~/notes/tmux-session-namer.py >> ~/log",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.is_managed(cmd), f"would rewrite: {cmd}")


class TestSettingsPatch(unittest.TestCase):
    """The patch script edits the user's GLOBAL ~/.claude/settings.json.

    Sad paths matter more than the happy one here: the failure mode is losing
    every hook, permission and env var the user has configured. Each test runs
    the real extracted script against a fake HOME.
    """

    def _run(self, settings_text: str | None) -> tuple[subprocess.CompletedProcess, Path]:
        """Run the patch script against a throwaway HOME; return result + path."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        claude = Path(tmp) / ".claude"
        claude.mkdir(parents=True)
        settings = claude / "settings.json"
        if settings_text is not None:
            settings.write_text(settings_text, encoding="utf-8")
        result = subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
            [sys.executable, "-I", "-S", "-c", _settings_patch_source()],
            env={**os.environ, "HOME": tmp},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result, settings

    def test_wires_hook_into_empty_settings(self) -> None:
        """Happy path: a missing file gets a valid, wired settings.json."""
        result, settings = self._run(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        commands = [
            h["command"]
            for entry in data["hooks"]["UserPromptSubmit"]
            for h in entry["hooks"]
        ]
        self.assertTrue(any("tmux-session-namer.py" in c for c in commands))
        self.assertTrue(all("-I" in c.split() and "-S" in c.split() for c in commands))

    def test_preserves_unrelated_hooks_and_keys(self) -> None:
        session_start = [{"hooks": [{"type": "command", "command": "echo start"}]}]
        original: dict[str, Any] = {
            "env": {"SOME_VAR": "keep me"},
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {
                "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo unrelated"}]}],
                "SessionStart": session_start,
            },
        }
        result, settings = self._run(json.dumps(original))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["env"], {"SOME_VAR": "keep me"})
        self.assertEqual(data["permissions"], {"allow": ["Bash(ls:*)"]})
        self.assertEqual(data["hooks"]["SessionStart"], session_start)
        commands = [
            h["command"]
            for entry in data["hooks"]["UserPromptSubmit"]
            for h in entry["hooks"]
        ]
        self.assertIn("echo unrelated", commands)

    def test_is_idempotent(self) -> None:
        """A second run must not append a duplicate.

        A duplicate would run the namer twice per prompt — doubling both the
        cost and how often prompt text leaves the machine.
        """
        result, settings = self._run(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = settings.read_text(encoding="utf-8")

        second = subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
            [sys.executable, "-I", "-S", "-c", _settings_patch_source()],
            env={**os.environ, "HOME": str(settings.parent.parent)},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        namer = [
            h["command"]
            for entry in data["hooks"]["UserPromptSubmit"]
            for h in entry["hooks"]
            if "tmux-session-namer.py" in h["command"]
        ]
        self.assertEqual(len(namer), 1, f"wired {len(namer)} times: {namer}")
        self.assertEqual(json.loads(first), data)

    def test_upgrades_a_legacy_unisolated_entry_in_place(self) -> None:
        legacy = "python3 ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"
        result, settings = self._run(
            json.dumps({"hooks": {"UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": legacy}]}
            ]}})
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        namer = [
            h["command"]
            for entry in data["hooks"]["UserPromptSubmit"]
            for h in entry["hooks"]
            if "tmux-session-namer.py" in h["command"]
        ]
        self.assertEqual(len(namer), 1, "upgraded by appending instead of in place")
        self.assertIn("-I", namer[0].split())
        self.assertIn("-S", namer[0].split())

    def test_refuses_malformed_json_without_destroying_it(self) -> None:
        """Invalid JSON must abort, leaving the file byte-identical.

        Overwriting it would discard whatever the user was mid-way through
        editing, on top of every setting already in there.
        """
        broken = '{"hooks": {"UserPromptSubmit": [ this is not json'
        result, settings = self._run(broken)
        self.assertNotEqual(result.returncode, 0, "accepted malformed JSON")
        self.assertEqual(settings.read_text(encoding="utf-8"), broken)

    def test_preserves_file_mode(self) -> None:
        result, settings = self._run(json.dumps({"hooks": {}}))
        self.assertEqual(result.returncode, 0, result.stderr)
        settings.chmod(0o600)
        subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
            [sys.executable, "-I", "-S", "-c", _settings_patch_source()],
            env={**os.environ, "HOME": str(settings.parent.parent)},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(settings.stat().st_mode & 0o777, 0o600)

    def test_leaves_no_temp_file_behind(self) -> None:
        result, settings = self._run(json.dumps({"hooks": {}}))
        self.assertEqual(result.returncode, 0, result.stderr)
        strays = [p.name for p in settings.parent.iterdir() if p.name.startswith(".settings-")]
        self.assertEqual(strays, [], f"left temp files: {strays}")


class TestHookCadence(unittest.TestCase):
    """The hook must call `claude -p` once per 20 prompts — never more.

    Firing more often multiplies both the cost and the number of times prompt
    fragments leave the machine, which the skill's consent text quantifies.
    """

    CADENCE = 20
    HISTORY_CAP = 200

    def _run_hook(self, env: dict[str, str], prompt: str) -> None:
        subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
            [sys.executable, "-I", "-S", str(HOOK)],
            input=json.dumps({"session_id": "test-session", "prompt": prompt}),
            text=True,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def _make_env(self, tmp: str) -> tuple[dict[str, str], Path]:
        bindir = Path(tmp) / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        fired = Path(tmp) / "fired.log"

        stub = bindir / "claude"
        stub.write_text(f'#!/bin/sh\necho fired >> "{fired}"\necho a-name\n', encoding="utf-8")
        stub.chmod(0o755)
        tmux = bindir / "tmux"
        tmux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tmux.chmod(0o755)

        env = {
            **os.environ,
            "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
            "TMUX": "/tmp/fake-tmux,1,0",  # nosec B108 - a value, not a path we open
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        }
        return env, fired

    @staticmethod
    def _fired(log: Path) -> int:
        return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0

    def test_cadence_holds_past_the_history_cap(self) -> None:
        """The regression that started this: the history is trimmed to 200 lines
        and 200 % 20 == 0, so a cadence derived from the line count fired on
        every prompt once the file saturated."""
        prompts = self.HISTORY_CAP + 30
        with tempfile.TemporaryDirectory() as tmp:
            env, fired = self._make_env(tmp)
            for i in range(1, prompts + 1):
                self._run_hook(env, f"prompt {i}")
            self.assertEqual(self._fired(fired), prompts // self.CADENCE)

    def test_skips_rename_when_counter_cannot_be_written(self) -> None:
        """An unstorable counter must mean no rename, not a guessed count.

        Guessing lands on exactly the cap at a saturated history, which fires
        every prompt — the same defect by another route.
        """
        with tempfile.TemporaryDirectory() as tmp:
            env, fired = self._make_env(tmp)
            for i in range(1, self.HISTORY_CAP + 5):
                self._run_hook(env, f"prompt {i}")
            baseline = self._fired(fired)

            counter = Path(env["XDG_CACHE_HOME"]) / "claude" / "count-test-session.txt"
            counter.unlink()
            counter.mkdir()  # a directory cannot be opened as a file

            for i in range(1, 41):
                self._run_hook(env, f"later prompt {i}")
            self.assertEqual(self._fired(fired) - baseline, 0)

    def test_history_is_capped_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env, _ = self._make_env(tmp)
            for i in range(1, self.HISTORY_CAP + 25):
                self._run_hook(env, f"prompt {i}")
            history = Path(env["XDG_CACHE_HOME"]) / "claude" / "prompts-test-session.txt"
            self.assertEqual(len(history.read_text(encoding="utf-8").splitlines()), self.HISTORY_CAP)
            self.assertEqual(history.stat().st_mode & 0o777, 0o600)

    def test_tightens_a_pre_existing_loose_history_file(self) -> None:
        """An existing history file must be tightened before anything is written.

        `os.open`'s mode argument applies only when it CREATES the file, so a
        `prompts-*.txt` left at 0644 by an earlier version kept receiving prompt
        text while readable by every other user — while the skill's consent text
        told the user it was 0600 and private. That makes the consent inaccurate
        about the single property that makes the capture acceptable.
        """
        for planted in (0o644, 0o666, 0o640):
            with self.subTest(mode=oct(planted)), tempfile.TemporaryDirectory() as tmp:
                env, _ = self._make_env(tmp)
                cache = Path(env["XDG_CACHE_HOME"]) / "claude"
                cache.mkdir(parents=True)
                os.chmod(cache, 0o700)

                history = cache / "prompts-test-session.txt"
                history.write_text("an older line\n", encoding="utf-8")
                os.chmod(history, planted)

                self._run_hook(env, "SECRET-probe-value")

                mode = history.stat().st_mode & 0o777
                self.assertEqual(
                    mode,
                    0o600,
                    f"history left at {oct(mode)} after planting {oct(planted)}; "
                    "prompt text is readable by other users",
                )
                self.assertIn(
                    "SECRET-probe-value",
                    history.read_text(encoding="utf-8"),
                    "the hook did not actually record, so the mode assertion is vacuous",
                )

    def test_tightens_a_pre_existing_loose_counter_file(self) -> None:
        """The counter holds no prompt text but still leaks typing volume."""
        with tempfile.TemporaryDirectory() as tmp:
            env, _ = self._make_env(tmp)
            cache = Path(env["XDG_CACHE_HOME"]) / "claude"
            cache.mkdir(parents=True)
            os.chmod(cache, 0o700)

            counter = cache / "count-test-session.txt"
            counter.write_text("5", encoding="utf-8")
            os.chmod(counter, 0o644)

            self._run_hook(env, "a prompt")

            mode = counter.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600, f"counter left at {oct(mode)}")

    def test_records_only_a_prefix_of_each_prompt(self) -> None:
        """The consent text promises the first 120 characters; hold it to that."""
        with tempfile.TemporaryDirectory() as tmp:
            env, _ = self._make_env(tmp)
            secret = "S" * 500
            self._run_hook(env, secret)
            history = Path(env["XDG_CACHE_HOME"]) / "claude" / "prompts-test-session.txt"
            recorded = history.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(len(recorded), 120)
            self.assertNotIn("S" * 121, history.read_text(encoding="utf-8"))

    CORRUPT_COUNTER_VALUES = ("", "   ", "not-a-number", "-5", "3.7", "9" * 21, "ë")

    def test_a_corrupt_counter_does_not_crash_the_prompt(self) -> None:
        """The hook runs on EVERY prompt, so an unhandled exception here would
        put a traceback in front of the user every time they type."""
        for corrupt in self.CORRUPT_COUNTER_VALUES:
            with self.subTest(value=corrupt), tempfile.TemporaryDirectory() as tmp:
                env, _ = self._make_env(tmp)
                self._run_hook(env, "seed the cache")
                counter = Path(env["XDG_CACHE_HOME"]) / "claude" / "count-test-session.txt"
                counter.write_text(corrupt, encoding="utf-8")

                result = subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
                    [sys.executable, "-I", "-S", str(HOOK)],
                    input=json.dumps({"session_id": "test-session", "prompt": "next"}),
                    text=True,
                    env=env,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_a_corrupt_counter_recovers_to_a_usable_integer(self) -> None:
        """Recovery re-seeds from the history length, so the cadence resumes
        tracking the real prompt number rather than restarting at zero."""
        for corrupt in self.CORRUPT_COUNTER_VALUES:
            with self.subTest(value=corrupt), tempfile.TemporaryDirectory() as tmp:
                env, _ = self._make_env(tmp)
                for i in range(5):
                    self._run_hook(env, f"seed {i}")
                counter = Path(env["XDG_CACHE_HOME"]) / "claude" / "count-test-session.txt"
                counter.write_text(corrupt, encoding="utf-8")

                self._run_hook(env, "after corruption")
                recovered = counter.read_text(encoding="utf-8").strip()
                self.assertTrue(
                    recovered.lstrip("-").isdigit(),
                    f"counter left unusable: {recovered!r}",
                )

    def test_a_corrupt_counter_does_not_cause_runaway_firing(self) -> None:
        """The damage to avoid is firing on every prompt, not firing at all.

        Re-seeding from the history length means the cadence stays honest: over
        a window of N prompts the hook fires about N/20 times, never N.
        """
        window = self.CADENCE * 2
        for corrupt in self.CORRUPT_COUNTER_VALUES:
            with self.subTest(value=corrupt), tempfile.TemporaryDirectory() as tmp:
                env, fired = self._make_env(tmp)
                self._run_hook(env, "seed the cache")
                counter = Path(env["XDG_CACHE_HOME"]) / "claude" / "count-test-session.txt"
                counter.write_text(corrupt, encoding="utf-8")

                before = self._fired(fired)
                for i in range(window):
                    self._run_hook(env, f"after corruption {i}")
                fires = self._fired(fired) - before
                self.assertLessEqual(
                    fires,
                    window // self.CADENCE + 1,
                    f"fired {fires} times in {window} prompts — cadence lost",
                )

    def test_handles_a_prompt_that_is_not_json(self) -> None:
        """Malformed stdin must not raise; the hook is on the prompt path."""
        with tempfile.TemporaryDirectory() as tmp:
            env, fired = self._make_env(tmp)
            for payload in ("", "not json at all", "[]", '{"no_prompt_key": 1}'):
                with self.subTest(payload=payload):
                    result = subprocess.run(  # nosec B603 - fixed argv, no shell, test-owned script
                        [sys.executable, "-I", "-S", str(HOOK)],
                        input=payload,
                        text=True,
                        env=env,
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(self._fired(fired), 0)

    def test_does_nothing_outside_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env, fired = self._make_env(tmp)
            env.pop("TMUX")
            for i in range(1, self.CADENCE + 5):
                self._run_hook(env, f"prompt {i}")
            self.assertEqual(self._fired(fired), 0)
            cache = Path(env["XDG_CACHE_HOME"]) / "claude"
            self.assertFalse(cache.exists(), "wrote cache files while not in tmux")


if __name__ == "__main__":
    unittest.main()
