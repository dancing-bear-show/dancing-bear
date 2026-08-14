"""Structural tests for the calendars CLI's built parser: expected subcommands exist.

Note: calendars.agentic._get_parser() also builds this parser but does so via
`calendars.__main__.app` (a stale path — `app` now lives in `calendars.cli.main`
and is no longer re-exported from `__main__`). That indirection currently fails
and is silently swallowed by core.agentic.cached_parser_loader's broad
except-Exception-return-None, so calendar agentic-capsule/CLI-tree/flow-map
output silently omits CLI structure in this environment. That's a production
bug in src/calendars/agentic.py, out of scope for this test file — tracked
separately. This file imports the parser directly from calendars.cli.main to
stay independent of that bug.
"""
from __future__ import annotations

import unittest

from calendars.cli.main import app


def _has_subcommand(parser, path):
    cur = parser
    for name in path:
        sub = None
        for act in getattr(cur, "_actions", []):
            if act.__class__.__name__.endswith("SubParsersAction"):
                sub = act
                break
        if not sub:
            return False
        cur = getattr(sub, "choices", {}).get(name)
        if cur is None:
            return False
    return True


class TestCLIParserSubcommands(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = app.build_parser()

    def test_outlook_add_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["outlook", "add"]))

    def test_outlook_add_recurring_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["outlook", "add-recurring"]))

    def test_outlook_reminders_exists(self):
        # Either reminders-off or reminders-set may exist depending on version.
        exists = _has_subcommand(self.parser, ["outlook", "reminders-off"]) or _has_subcommand(
            self.parser, ["outlook", "reminders-set"]
        )
        self.assertTrue(exists)

    def test_gmail_scan_classes_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["gmail", "scan-classes"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
