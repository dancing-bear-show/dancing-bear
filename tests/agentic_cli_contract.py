"""Shared contract for the CLI-level ``--agentic`` flag.

Distinct from :mod:`tests.agentic_builder_contract`, which covers the
``<domain>/agentic.py`` builder functions. This one covers the other end: the
CLI surface every app exposes via ``main(["--agentic"])``, plus the
``--agentic-format`` and ``--agentic-compact`` modifiers.

Fourteen apps were testing this by hand and, as usual, unevenly -- ``--agentic``
appeared in 16 test files while ``--agentic-format``/``--agentic-compact``
appeared in 11.

Usage::

    class TestWifiAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
        MODULE_PATH = "wifi.__main__"
        APP_ID = "wifi"

The invariants were derived by running all fourteen apps rather than assumed:
every one returns 0, opens with ``agentic: <app_id>``, emits exactly the keys in
:data:`EXPECTED_SCHEMA_KEYS`, and produces strictly smaller output under
``--agentic-compact``. The key set is named rather than counted here so the
prose cannot drift from the constant.

The byte-count assertions matter more than they look. ``core.agentic`` swallows
a failed parser import and returns ``None``, so a broken capsule degrades to a
short stub rather than raising -- a test that only checks the exit code passes
against a capsule that has lost its entire CLI tree.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json

#: Keys every app's JSON schema exposes at the top level. Verified identical
#: across all fourteen apps, so this is asserted as an exact set rather than a
#: subset -- a key silently appearing or disappearing is itself a drift signal.
EXPECTED_SCHEMA_KEYS = frozenset(
    {"description", "epilog", "options", "prog", "subcommands", "usage"}
)

#: Floor for a capsule that actually rendered. Real capsules run from ~380 bytes
#: (sheets) to ~37KB (mail); anything below this is a stub from a swallowed import.
MIN_CAPSULE_BYTES = 200


class AgenticCLIContractMixin:
    """Contract tests for an app's ``--agentic`` CLI surface.

    Subclasses must set :attr:`MODULE_PATH` and :attr:`APP_ID`, and must also
    inherit from ``unittest.TestCase``.
    """

    #: Importable module exposing ``main(argv)``, e.g. ``"wifi.__main__"``.
    MODULE_PATH: str
    #: Identifier the capsule announces itself with. Not always the package
    #: name -- ``calendars`` emits ``agentic: calendar`` (singular).
    APP_ID: str

    def _run(self, argv: list[str]) -> tuple[int, str]:
        module = importlib.import_module(self.MODULE_PATH)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.main(argv)
        return rc, buf.getvalue()

    # -- plain --agentic -------------------------------------------------

    def test_agentic_returns_zero_and_announces_the_app(self):
        rc, out = self._run(["--agentic"])
        self.assertEqual(rc, 0)
        self.assertIn(f"agentic: {self.APP_ID}", out)

    def test_agentic_output_is_substantial(self):
        """Guards the swallowed-import failure mode, which exits 0 regardless."""
        _, out = self._run(["--agentic"])
        self.assertGreater(
            len(out),
            MIN_CAPSULE_BYTES,
            f"capsule is only {len(out)} bytes -- likely a stub from a failed parser import",
        )

    # -- --agentic-format json -------------------------------------------

    def test_json_format_returns_zero_and_parses(self):
        rc, out = self._run(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0)
        json.loads(out)

    def test_json_schema_exposes_the_shared_keys(self):
        _, out = self._run(["--agentic", "--agentic-format", "json"])
        self.assertEqual(EXPECTED_SCHEMA_KEYS, set(json.loads(out)))

    def test_json_schema_names_the_prog(self):
        _, out = self._run(["--agentic", "--agentic-format", "json"])
        self.assertTrue(json.loads(out)["prog"], "prog must not be empty")

    def test_json_schema_declares_subcommands_or_options(self):
        """A schema with neither is a parser that failed to introspect."""
        schema = json.loads(self._run(["--agentic", "--agentic-format", "json"])[1])
        self.assertTrue(
            schema["subcommands"] or schema["options"],
            "schema exposes neither subcommands nor options",
        )

    # -- --agentic-compact -----------------------------------------------

    def test_compact_returns_zero_and_parses(self):
        rc, out = self._run(["--agentic", "--agentic-format", "json", "--agentic-compact"])
        self.assertEqual(rc, 0)
        json.loads(out)

    def test_compact_is_smaller_than_full(self):
        """--agentic-compact exists to save tokens; it must actually do so."""
        _, full = self._run(["--agentic", "--agentic-format", "json"])
        _, compact = self._run(["--agentic", "--agentic-format", "json", "--agentic-compact"])
        self.assertLess(len(compact), len(full))

    def test_compact_still_names_the_prog(self):
        """Compaction strips low-value fields, not the app's identity."""
        _, out = self._run(["--agentic", "--agentic-format", "json", "--agentic-compact"])
        self.assertTrue(json.loads(out)["prog"])
