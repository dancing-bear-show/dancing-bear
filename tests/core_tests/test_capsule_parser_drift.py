"""Every command a hand-authored capsule advertises must exist in the live CLI.

Two `--agentic` output paths exist and they are not equally trustworthy:

* ``--agentic-format json`` is built by introspecting the real parser
  (``core.agentic_schema.build_schema_json``), so it cannot drift.
* ``--agentic-format text`` / ``yaml`` render a hand-written capsule in each
  package's ``agentic.py``. Nothing tied that prose to the parser, so a renamed
  flag left the capsule advertising a command that errors.

That is not hypothetical. PR #291 shipped ``./bin/worker show --id <job-id>``
(``id`` is positional, so the flag form exits non-zero) and
``./bin/telemetry rules --list`` (``No such option: --list``) through a green
suite of 11,588 tests, because the prose path had no check at all. Agents are
told to prefer these capsules over ``--help``, so a wrong command there is worse
than a wrong comment — it is a machine-readable instruction to run something
broken.

This test closes that gap: it parses every ``./bin/...`` invocation out of each
capsule and asserts the subcommand path and every long flag resolve against that
CLI's own JSON schema.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every app with a hand-authored capsule, mapped to the command prefixes its
# capsule may use. The json path needs no policing, so only the prose path is
# listed here. The first prefix is also how the schema is fetched.
#
# Two subtleties, both learned from real misses:
#   - The invocation is not always ``./bin/<app>``. desk and resume ship no
#     wrapper (``python3 -m desk``, ``./bin/assistant resume``), and their
#     capsules once advertised ``./bin/desk-assistant`` / ``./bin/resume-assistant``,
#     neither of which exists.
#   - One capsule may use several spellings of the same CLI. mail advertises
#     both ``./bin/mail`` and the legacy ``./bin/mail-assistant``; listing only
#     one silently skips every command under the other.
APPS = {
    "apple-music-assistant": [["./bin/apple-music-assistant"]],
    "calendar": [["./bin/calendar"], ["./bin/calendar-assistant"]],
    "charts": [["./bin/charts"]],
    "desk": [["python3", "-m", "desk"]],
    "diagrams": [["./bin/diagrams"]],
    "mail": [["./bin/mail"], ["./bin/mail-assistant"]],
    "maker": [["./bin/maker"]],
    "phone": [["./bin/phone"], ["./bin/phone-assistant"]],
    "qlty-assistant": [["./bin/qlty-assistant"]],
    "resume": [["./bin/assistant", "resume"]],
    "schedule": [["./bin/schedule"], ["./bin/schedule-assistant"]],
    "sheets": [["./bin/sheets"]],
    "slides": [["./bin/slides"]],
    "telemetry": [["./bin/telemetry"]],
    "whatsapp": [["./bin/whatsapp"]],
    "wifi": [["./bin/wifi"], ["./bin/wifi-assistant"]],
    "worker": [["./bin/worker"]],
    "workflow": [["./bin/workflow"]],
}

# A command line: a leading `./bin/x` or `python3 -m pkg`, then every following
# token on that line.
#
# The trailing token class must accept path-like values (`out/plan.yaml`,
# `~/Downloads`, `'{}'`). An earlier `[\w.@=-]+` stopped at the first `/`, so
# `desk apply --plan out/desk.plan.yaml --dry-run` truncated to `... --plan out`
# and every flag after a path went unchecked — a false negative that hides
# exactly the drift this test exists to catch.
#
# `[^\S\n]` keeps a match on one line: plain `\s` would run past a newline and
# swallow the next capsule entry, reporting its tokens as flags of the previous
# command.
# Tokens exclude backticks, and the run stops at the first token containing a
# comma or a closing bracket — that is where a command embedded in prose ends.
# Without that, the workflow note "file arguments are positional
# (./bin/workflow run <file>), not --input" swallows ", not --input" and reports
# --input as drift, when the note exists precisely to say it is not a flag.
_INVOCATION = re.compile(
    r"(?:\./bin/[\w.-]+|python3[^\S\n]+-m[^\S\n]+[\w.]+)"
    r"(?:[^\S\n]+[^\s`,;)\]}]+)*"
)

# Capsule text is prose: a command can end in a backtick, a comma, or close a
# parenthesis the command never opened. Strip that before matching a token
# against the parser, or `--json` reads as `--json\`` and is reported missing.
#
# `>` is deliberately absent: stripping it turns the placeholder `<file>` into
# `<file`, which no longer matches _NOT_A_SUBCOMMAND and leaks in as a real
# subcommand name. Placeholders are discarded whole, so they need their closing
# bracket intact.
_TRAILING_PROSE = "),.;:`'\"]}"

# argparse and Click both synthesise --help; it is never in the emitted schema.
_UNIVERSAL_FLAGS = frozenset({"--help"})

# Tokens that look like subcommands but are placeholders or shell noise.
# Decomposed into individual patterns for readability and to stay within the
# S5843 complexity limit; _is_noise() checks them in order.
#
# Dots do NOT disqualify a token: this repo's Outlook and config subcommands are
# dot-separated (`rules.plan`, `derive.filters`, `auth.ensure`), so a blanket
# "contains a dot means filename" rule would silently skip exactly the commands
# most prone to drift. Only a dot with a known file extension is treated as a
# path, and `/` always is.
_NOISE_ANGLE = re.compile(r"^<.*>$")           # <job-id>, <file.yaml>
_NOISE_BRACKET = re.compile(r"^\[.*\]$")       # [options]
_NOISE_BRACE = re.compile(r"^\{.*\}$")         # {a,b}
_NOISE_PATH = re.compile(r".*/")               # paths: out/x.yaml, ~/.config/x
_NOISE_EXT = re.compile(
    r"\.(ya?ml|json|md|py|csv|txt|png|svg|pptx|xlsx|mmd|docx|pdf)$"
)                                               # bare filenames with known extensions
_NOISE_NUMBER = re.compile(r"^\d+[a-z]?$")    # bare numbers and durations: 7, 7d
_NOISE_QUOTED = re.compile(r"'")               # quoted fragments: any token containing a single-quote


def _is_noise(token: str) -> bool:
    """Return True when ``token`` is a placeholder or shell noise, not a subcommand."""
    return bool(
        _NOISE_ANGLE.search(token)
        or _NOISE_BRACKET.search(token)
        or _NOISE_BRACE.search(token)
        or _NOISE_PATH.search(token)
        or _NOISE_EXT.search(token)
        or _NOISE_NUMBER.match(token)
        or _NOISE_QUOTED.search(token)
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # Two ways this subprocess can silently test the wrong code, both of which
    # surface as a passing test rather than an error:
    #
    #   1. PYTHONPATH. Unpinned, `-m desk` imports whatever is installed (or an
    #      inherited path from another checkout), so the capsule under test is
    #      rendered from code this run did not change.
    #   2. The interpreter. A literal `python3` is resolved from PATH, which in
    #      this repo points at the MAIN checkout's venv even when the suite runs
    #      from a worktree — verified: `which python3` gives
    #      dancing-bear/.venv/bin/python3 while the suite runs
    #      .claude/worktrees/<wt>/.venv/bin/python. It may also be absent or a
    #      different version entirely. sys.executable is the interpreter running
    #      this test, which is the one whose behaviour we mean to check.
    #
    # APPS keeps the literal "python3" because the capsule text says python3;
    # only the spawned argv is rewritten.
    argv = [sys.executable if a == "python3" else a for a in args]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(  # nosec B603 - argv is constructed from APPS (hardcoded repo-local commands) with python3 rewritten to sys.executable; no user input reaches here
        argv, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, env=env
    )


@lru_cache(maxsize=None)
def _schema(invocation: tuple[str, ...]) -> dict:
    proc = _run([*invocation, "--agentic", "--agentic-format", "json"])
    shown = " ".join(invocation)
    if proc.returncode != 0:
        raise AssertionError(
            f"{shown} --agentic --agentic-format json exited "
            f"{proc.returncode}: {proc.stderr.strip()[:300]}"
        )
    return json.loads(proc.stdout)


@lru_cache(maxsize=None)
def _capsule(invocation: tuple[str, ...]) -> str:
    proc = _run([*invocation, "--agentic"])
    shown = " ".join(invocation)
    if proc.returncode != 0:
        raise AssertionError(
            f"{shown} --agentic exited {proc.returncode}: "
            f"{proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def _is_boolean(opt: dict) -> bool:
    """True when this option takes no value.

    argparse reports ``nargs: 0`` for store_true/store_false; Click sets
    ``is_flag``. Getting this wrong in either direction corrupts parsing: treat
    a boolean as value-taking and it swallows the following subcommand.
    """
    if opt.get("is_flag") is True:
        return True
    if opt.get("nargs") == 0:
        return True
    action = opt.get("action") or ""
    return "StoreTrue" in action or "StoreFalse" in action


def _flags_of_node(node: dict, booleans: set[str]) -> set[str]:
    """Collect all long-flag names from a schema node's options list.

    Populates ``booleans`` in place with any flag that takes no value.
    """
    found: set[str] = set()
    for opt in node.get("options") or []:
        names = [f for f in (opt.get("flags") or []) if f.startswith("--")]
        name = opt.get("name")
        if isinstance(name, str) and name.startswith("--"):
            names.append(name)
        found.update(names)
        if _is_boolean(opt):
            booleans.update(names)
    return found


def _walk_schema(
    node: dict,
    prefix: str,
    index: dict[str, set[str]],
    booleans: set[str],
) -> None:
    """Recursively index every sub-path and its valid flags."""
    index.setdefault(prefix, set()).update(_flags_of_node(node, booleans))
    children = (node.get("subcommands") or []) + (node.get("commands") or [])
    for child in children:
        name = child.get("name")
        if not name:
            continue
        _walk_schema(child, f"{prefix} {name}".strip(), index, booleans)


def _index(schema: dict) -> tuple[dict[str, set[str]], set[str]]:
    """Return (sub path -> long flags valid there, all boolean long flags).

    Root options live under "". Handles both schema shapes: argparse nests
    under ``subcommands``, the Click emitter (telemetry) uses a flat
    ``commands`` list.
    """
    index: dict[str, set[str]] = {}
    booleans: set[str] = set()
    _walk_schema(schema, "", index, booleans)
    return index, booleans


def _match_prefix(
    parts: list[str], prefixes: list[list[str]]
) -> list[str] | None:
    """Return the tokens after the matched prefix, or None if no prefix matches."""
    for prefix in prefixes:
        if parts[: len(prefix)] == prefix:
            return parts[len(prefix) :]
    return None


def _parse_tokens(
    tokens: list[str], booleans: frozenset[str] | set[str]
) -> tuple[list[str], list[str]]:
    """Classify tokens into (subcommand names, long flags).

    Only the token immediately after a value-taking flag is its value.
    Two ways to get this wrong, both of which silently drop real tokens:
    treating every later bare word as a value loses subcommands (global
    flags precede the subcommand: ``mail --profile p messages search``),
    and treating a boolean as value-taking swallows the next subcommand
    (``mail --dry-run labels plan`` would parse as just ``plan``). The
    parser's own schema says which flags take values.
    """
    subs: list[str] = []
    flags: list[str] = []
    expect_value = False
    for raw_token in tokens:
        token = raw_token.rstrip(_TRAILING_PROSE)
        if not token:
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            flags.append(name)
            expect_value = "=" not in token and name not in booleans
        elif expect_value:
            expect_value = False
        elif not _is_noise(token):
            subs.append(token)
    return subs, flags


def _invocations(
    capsule: str,
    prefixes: list[list[str]],
    booleans: frozenset[str] | set[str] = frozenset(),
) -> list[tuple[list[str], list[str], str]]:
    """Return (subcommand tokens, long flags, raw text) per matching command.

    Only commands starting with one of this app's own prefixes. Capsules
    routinely cite sibling wrappers (``./bin/llm agentic`` inside the mail
    capsule) as related reading; checking those against *this* CLI's parser
    would report every one as a missing subcommand. Each app's own test covers
    its own commands.
    """
    out = []
    for match in _INVOCATION.finditer(capsule):
        raw = match.group(0)
        tokens = _match_prefix(raw.split(), prefixes)
        if tokens is None:
            continue
        subs, flags = _parse_tokens(tokens, booleans)
        out.append((subs, flags, raw))
    return out


def _resolve_path(subs: list[str], known: set[str]) -> str | None:
    """Find the deepest known subcommand path for ``subs``, or None if unknown."""
    for depth in range(len(subs), 0, -1):
        candidate = " ".join(subs[:depth])
        if candidate in known:
            return candidate
    return None


def _collect_problems(
    checked: list[tuple[list[str], list[str], str]],
    index: dict[str, set[str]],
) -> list[str]:
    """Return a list of drift problems found in the checked invocations."""
    known = set(index)
    problems: list[str] = []
    for subs, flags, raw in checked:
        path = _resolve_path(subs, known)
        if path is None:
            if subs:
                problems.append(
                    f"subcommand {' '.join(subs)!r} does not exist  ({raw})"
                )
            continue
        valid = index.get(path, set()) | index.get("", set()) | _UNIVERSAL_FLAGS
        for flag in flags:
            if flag not in valid:
                where = f"'{path}'" if path else "the top level"
                problems.append(f"flag {flag!r} does not exist on {where}  ({raw})")
    return problems


class CapsuleMatchesParser(unittest.TestCase):
    """Each capsule's advertised commands must resolve against its own parser."""

    maxDiff = None

    def _assert_no_drift(self, app: str) -> None:
        prefixes = APPS[app]
        primary = prefixes[0]
        shown = " ".join(primary)
        index, booleans = _index(_schema(tuple(primary)))

        capsule = _capsule(tuple(primary))
        checked = _invocations(capsule, prefixes, booleans)

        # Guard against vacuous coverage: a capsule whose commands use a spelling
        # no prefix matches parses to zero invocations and passes without
        # asserting anything. That is how `desk` sat green while its capsule
        # still advertised `./bin/desk-assistant`, a wrapper that never existed.
        #
        # "Advertises nothing" is a different, legitimate state — calendar,
        # schedule and apple-music ship header-only capsules. Distinguish them by
        # asking whether the capsule contains any command-shaped text at all.
        if not checked and _INVOCATION.search(capsule):
            unmatched = sorted(
                {m.group(0).split()[0] for m in _INVOCATION.finditer(capsule)}
            )
            self.fail(
                f"{shown} --agentic advertises commands, but none match a prefix "
                f"in APPS[{app!r}], so this test asserted nothing.\n"
                f"Add the missing prefix (or fix the capsule). Seen: {unmatched}"
            )

        problems = _collect_problems(checked, index)
        if problems:
            self.fail(
                f"{shown} --agentic advertises commands its parser rejects.\n"
                "The capsule in that package's agentic.py has drifted from the CLI;\n"
                "fix the capsule to match --help (not the other way around).\n  - "
                + "\n  - ".join(problems)
            )


class SubprocessEnvironment(unittest.TestCase):
    """The subprocess must run this checkout's code under this interpreter.

    Both of these fail as a *passing* test rather than an error, which is why
    they are asserted rather than assumed.
    """

    def test_spawns_the_interpreter_running_this_suite(self):
        # A literal "python3" resolves from PATH, which in this repo points at
        # the main checkout's venv even when the suite runs from a worktree.
        proc = _run(["python3", "-c", "import sys; print(sys.executable)"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), sys.executable)

    def test_imports_resolve_to_this_checkout(self):
        proc = _run(["python3", "-c", "import desk; print(desk.__file__)"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(
            proc.stdout.strip().startswith(str(REPO_ROOT / "src")),
            f"desk imported from {proc.stdout.strip()!r}, not {REPO_ROOT / 'src'}",
        )


class InvocationParsing(unittest.TestCase):
    """The parser inside this test file, checked on its own known-hard cases.

    Every case here is a bug this checker actually shipped. A parsing slip does
    not fail loudly — it drops tokens and reports "no drift", which looks
    identical to a clean capsule.
    """

    def _parse(self, text: str, prefix: str, booleans=frozenset()):
        got = _invocations(text, [[prefix]], booleans)
        self.assertEqual(len(got), 1, f"expected one invocation in {text!r}")
        subs, flags, _ = got[0]
        return subs, flags

    def test_boolean_flag_does_not_swallow_the_next_subcommand(self):
        subs, flags = self._parse(
            "./bin/mail --dry-run labels plan\n", "./bin/mail", {"--dry-run"}
        )
        self.assertEqual(subs, ["labels", "plan"])
        self.assertEqual(flags, ["--dry-run"])

    def test_value_flag_still_consumes_its_value(self):
        subs, flags = self._parse(
            "./bin/mail --profile p messages search\n", "./bin/mail"
        )
        self.assertEqual(subs, ["messages", "search"])
        self.assertEqual(flags, ["--profile"])

    def test_consecutive_boolean_flags_are_both_seen(self):
        subs, flags = self._parse(
            "./bin/wifi diagnose --no-trace --no-http\n",
            "./bin/wifi",
            {"--no-trace", "--no-http"},
        )
        self.assertEqual(subs, ["diagnose"])
        self.assertEqual(flags, ["--no-trace", "--no-http"])

    def test_flags_after_a_path_value_are_not_lost(self):
        subs, flags = self._parse(
            "./bin/desk apply --plan desk.plan.yaml --dry-run\n", "./bin/desk"
        )
        self.assertEqual(subs, ["apply"])
        self.assertIn("--dry-run", flags)

    def test_dotted_subcommands_are_not_mistaken_for_filenames(self):
        subs, _ = self._parse(
            "./bin/mail outlook rules.plan --config f.yaml\n", "./bin/mail"
        )
        self.assertEqual(subs, ["outlook", "rules.plan"])

    def test_match_stops_at_end_of_line(self):
        got = _invocations(
            "./bin/mail labels plan\n./bin/mail filters sync\n", [["./bin/mail"]]
        )
        self.assertEqual([subs for subs, _, _ in got], [["labels", "plan"], ["filters", "sync"]])

    def test_prose_after_a_command_is_not_parsed_as_flags(self):
        subs, flags = self._parse(
            "positional (./bin/workflow run <file>), not --input\n", "./bin/workflow"
        )
        self.assertEqual(subs, ["run"])
        self.assertNotIn("--input", flags)


def _attach(app: str) -> None:
    def test(self, _app=app):
        self._assert_no_drift(_app)

    test.__name__ = f"test_{app.replace('-', '_')}_capsule_matches_parser"
    test.__doc__ = f"{' '.join(APPS[app][0])} --agentic advertises only real commands."
    setattr(CapsuleMatchesParser, test.__name__, test)


for _app in APPS:
    _attach(_app)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
