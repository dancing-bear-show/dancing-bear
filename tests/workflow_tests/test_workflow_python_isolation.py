"""Shipped workflows must not start an unisolated ``python -c`` interpreter.

Python imports ``sitecustomize`` from every ``PYTHONPATH`` entry during
startup, before the ``-c`` body runs. A workflow agent inherits the session's
environment, which may name a different checkout, so a bare ``python3 -c`` in
a stage prompt runs that tree's startup hook. CLAUDE.md states the rule for
hooks; this test holds the workflow catalog to it.

An invocation is safe when it either passes ``-I`` (ignores ``PYTHONPATH``;
add ``-S`` for stdlib-only bodies) or replaces the inherited value with this
checkout's own ``src`` via a ``PYTHONPATH="$PWD/src"`` prefix, the house form
for import probes.

Scanning is textual on purpose: commands live in descriptions, criteria and
quoted strings alike, including Markdown code spans. Every mention of the
unisolated form counts, with or without a program after ``-c``: "confirm it
parses by running `python3 -c` with yaml.safe_load" is an instruction the
agent turns into a bare command. There is no prose exemption, so a warning
about the hazard must describe it ("an inline Python one-liner") rather than
spell the bare form.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / "workflows"

# An interpreter — a literal python/python3 (optionally .venv/bin/) or a shell
# variable naming one ($PY, "${PYTHON}") — then its flags, then -c as a whole
# token. Flags include the argument-taking -X/-W forms so `-X utf8` cannot hide
# the -c behind it.
_INVOCATION = re.compile(
    r"(?<![\w.-])(?P<interp>(?:\.venv/bin/)?python3?|\$\{?\w*(?:PY|py)\w*\}?\"?)"
    r"(?P<flags>(?:[ \t]+-(?:[XW][ \t]*\S+|[A-Za-z]+))*?)[ \t]+-c(?![\w-])"
)
_PINNED_PREFIX = re.compile(r'PYTHONPATH="\$(?:PWD|\(pwd\))/src"[ \t]+$')


def unisolated_invocations(text: str) -> list[int]:
    """Return 1-based line numbers of ``python -c`` mentions lacking isolation."""
    hits = []
    for m in _INVOCATION.finditer(text):
        if re.search(r"-\w*I", m.group("flags")):
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _PINNED_PREFIX.search(text[line_start : m.start()]):
            continue
        hits.append(text.count("\n", 0, m.start()) + 1)
    return hits


class TestScanner(unittest.TestCase):
    def test_flags_bare_forms(self):
        for text in (
            'python3 -c "import json"',
            "  .venv/bin/python -c 'import fitz'",
            'x=$(python3 -c "print(1)")',
            'summary: python3 -c \\"import json\\"',
            "python3 -c \\\n  'import os'",
            'python3 -B -c "import os"',
            'OTHER=1 python3 -c "import os"',
            'Run `python3 -c "import json"` to check it.',
            'never use a bare `python3 -c "import worker"` here',
            '- `.venv/bin/python -c "import fitz"`',
            "confirm it parses by running `python3 -c` with yaml.safe_load",
            "Do NOT reach for an inline `python3 -c` here.",
            "parse with awk or python3 -c (no grep -P).",
            "into a `python -c`\n",
            '$PY -c "import os"',
            '"${PYTHON}" -c "import os"',
            'python3 -X utf8 -c "import os"',
        ):
            with self.subTest(text=text):
                self.assertEqual(unisolated_invocations(text), [1])

    def test_accepts_isolated_and_pinned_forms(self):
        for text in (
            'python3 -I -S -c "import json"',
            '.venv/bin/python -I -c "import fitz"',
            'python3 -IS -c "import json"',
            'PYTHONPATH="$PWD/src" python3 -c "import worker"',
            'PYTHONPATH="$(pwd)/src" .venv/bin/python -c \\\n  "import fitz"',
            "confirm it parses by running `python3 -I -c` with yaml.safe_load",
            'Run `python3 -I -S -c "import json"` to check it.',
            'run `PYTHONPATH="$PWD/src" python3 -c "import worker"`',
            'python3 -X utf8 -I -c "import os"',
            '$PY -I -S -c "import os"',
            "Do NOT reach for an inline Python one-liner here.",
            "python3 -m unittest -c",
            "python3 -command",
        ):
            with self.subTest(text=text):
                self.assertEqual(unisolated_invocations(text), [])

    def test_reports_the_offending_line(self):
        self.assertEqual(unisolated_invocations('a\nb\n  python3 -c "x"\n'), [3])


class TestShippedWorkflows(unittest.TestCase):
    def test_no_unisolated_python_c(self):
        paths = sorted(WORKFLOWS_DIR.rglob("*.yaml"))
        self.assertGreater(len(paths), 50, "workflow catalog not found")
        offenders = [
            f"{p.relative_to(REPO_ROOT)}:{n}"
            for p in paths
            for n in unisolated_invocations(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            offenders,
            [],
            'use python3 -I -S -c (stdlib only), -I (needs site-packages), or a PYTHONPATH="$PWD/src" prefix',
        )


if __name__ == "__main__":
    unittest.main()
