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
import unittest
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
_TRAILING_PROSE = ")>,.;:`'\"]}"

# argparse and Click both synthesise --help; it is never in the emitted schema.
_UNIVERSAL_FLAGS = frozenset({"--help"})

# Tokens that look like subcommands but are placeholders or shell noise.
#
# Dots do NOT disqualify a token: this repo's Outlook and config subcommands are
# dot-separated (`rules.plan`, `derive.filters`, `auth.ensure`), so a blanket
# "contains a dot means filename" rule would silently skip exactly the commands
# most prone to drift. Only a dot with a known file extension is treated as a
# path, and `/` always is.
_NOT_A_SUBCOMMAND = re.compile(
    r"""^(
        <.*>                            # <job-id>, <file.yaml>
        | \[.*\]                        # [options]
        | \{.*\}                        # {a,b}
        | .*/.*                         # paths: out/x.yaml, ~/.config/x
        | .*\.(ya?ml|json|md|py|csv|txt|png|svg|pptx|xlsx|mmd|docx|pdf)$
        | \d+[a-z]?                     # bare numbers and durations: 7, 7d
        | '.*|.*'                       # quoted fragments
    )$""",
    re.VERBOSE,
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # Pin PYTHONPATH to this checkout. `python3 -m desk` otherwise resolves via
    # whatever is installed (or an inherited PYTHONPATH from another checkout),
    # so the subprocess renders a capsule from code this test did not change —
    # a false green indistinguishable from a real one.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, env=env
    )


def _schema(invocation: list[str]) -> dict:
    proc = _run([*invocation, "--agentic", "--agentic-format", "json"])
    shown = " ".join(invocation)
    if proc.returncode != 0:
        raise AssertionError(
            f"{shown} --agentic --agentic-format json exited "
            f"{proc.returncode}: {proc.stderr.strip()[:300]}"
        )
    return json.loads(proc.stdout)


def _capsule(invocation: list[str]) -> str:
    proc = _run([*invocation, "--agentic"])
    shown = " ".join(invocation)
    if proc.returncode != 0:
        raise AssertionError(
            f"{shown} --agentic exited {proc.returncode}: "
            f"{proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def _index(schema: dict) -> dict[str, set[str]]:
    """Map "sub path" -> long flags valid there. Root options live under "".

    Handles both schema shapes: argparse nests under ``subcommands``, the Click
    emitter (telemetry) uses a flat ``commands`` list.
    """
    index: dict[str, set[str]] = {}

    def flags_of(node: dict) -> set[str]:
        found: set[str] = set()
        for opt in node.get("options") or []:
            for flag in opt.get("flags") or []:
                if flag.startswith("--"):
                    found.add(flag)
            name = opt.get("name")
            if isinstance(name, str) and name.startswith("--"):
                found.add(name)
        return found

    def walk(node: dict, prefix: str) -> None:
        index.setdefault(prefix, set()).update(flags_of(node))
        for child in (node.get("subcommands") or []) + (node.get("commands") or []):
            name = child.get("name")
            if not name:
                continue
            walk(child, f"{prefix} {name}".strip())

    walk(schema, "")
    return index


def _invocations(
    capsule: str, prefixes: list[list[str]]
) -> list[tuple[list[str], list[str], str]]:
    """Yield (subcommand tokens, long flags, raw text) per matching command.

    Only commands starting with one of this app's own prefixes. Capsules
    routinely cite sibling wrappers (``./bin/llm agentic`` inside the mail
    capsule) as related reading; checking those against *this* CLI's parser
    would report every one as a missing subcommand. Each app's own test covers
    its own commands.
    """
    out = []
    for match in _INVOCATION.finditer(capsule):
        raw = match.group(0)
        parts = raw.split()
        for prefix in prefixes:
            if parts[: len(prefix)] == prefix:
                tokens = parts[len(prefix) :]
                break
        else:
            continue
        subs, flags = [], []
        # Only the token immediately after a flag is its value. Treating every
        # later bare word as a value loses real subcommands, since global flags
        # precede the subcommand here: `mail --profile p messages search`.
        expect_value = False
        for token in tokens:
            token = token.rstrip(_TRAILING_PROSE)
            if not token:
                continue
            if token.startswith("--"):
                flags.append(token.split("=", 1)[0])
                expect_value = "=" not in token
            elif expect_value:
                expect_value = False
            elif not _NOT_A_SUBCOMMAND.match(token):
                subs.append(token)
        out.append((subs, flags, raw))
    return out


class CapsuleMatchesParser(unittest.TestCase):
    """Each capsule's advertised commands must resolve against its own parser."""

    maxDiff = None

    def _assert_no_drift(self, app: str) -> None:
        prefixes = APPS[app]
        primary = prefixes[0]
        shown = " ".join(primary)
        index = _index(_schema(primary))
        known = set(index)
        problems: list[str] = []

        capsule = _capsule(primary)
        checked = _invocations(capsule, prefixes)

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

        for subs, flags, raw in checked:
            path = ""
            for depth in range(len(subs), 0, -1):
                candidate = " ".join(subs[:depth])
                if candidate in known:
                    path = candidate
                    break
            else:
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

        if problems:
            self.fail(
                f"{shown} --agentic advertises commands its parser rejects.\n"
                "The capsule in that package's agentic.py has drifted from the CLI;\n"
                "fix the capsule to match --help (not the other way around).\n  - "
                + "\n  - ".join(problems)
            )


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
