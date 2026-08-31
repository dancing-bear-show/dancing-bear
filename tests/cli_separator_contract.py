"""Shared contract for the CLI ``--`` separator stripping behaviour.

``CLIApp.normalize_argv`` implements a documented public guarantee
(CLAUDE.md): "the ``--`` separator is now **optional** for all CLIApp-based
CLIs — ``src/core/cli_framework.py`` strips bare ``--`` tokens automatically."

The guarantee protects callers (primarily the workflow engine) that always
insert ``--`` before flag-like arguments, and human operators who follow the
POSIX convention of putting ``--`` before the subcommand to signal "no more
options for the shell". Any CLIApp-based app that pre-parses ``sys.argv``
itself, or that bypasses ``run_with_assistant``, would silently break this
contract and reject invocations like ``main(["--", "--agentic"])``.

**Unit coverage already in** ``tests/core_tests/test_cli_framework.py``
(class ``TestNormalizeArgv``):

- ``test_no_separator_unchanged`` — no ``--``, argv passes through unchanged
- ``test_strips_first_bare_separator`` — ``["search", "--", "--contains", "test"]``
  → ``["search", "--contains", "test"]``
- ``test_trailing_separator_preserved`` — ``["search", "--contains", "test", "--"]``
  → unchanged (trailing ``--`` is not the subcommand/flag separator)
- ``test_only_first_separator_stripped_second_preserved`` — POSIX semantics:
  only the first ``--`` is the "end of options" marker; any later ``--`` guards a
  positional value that looks like a flag and must be left in place
- ``test_empty_argv`` — no crash on empty list
- ``test_single_trailing_separator_preserved`` — a lone ``--`` is trailing by
  definition and is left unchanged

The invariants tested here do **not** duplicate the unit tests above. They
test a different, orthogonal property: that each real app's ``main()``
actually honours the contract end-to-end rather than breaking it through
custom argv pre-processing or bypassing ``run_with_assistant``. Concretely:

- ``main(["--agentic"])`` and ``main(["--", "--agentic"])`` must both return 0
- their stdout must be byte-identical — the ``--`` is transparent to the caller

The trailing-``--`` and double-``--`` semantics are covered at the unit level
and are **not** repeated here: running them through every app's ``main()``
would just exercise ``usage/error`` paths that depend on available subcommands,
not on the separator logic itself.

Invariants were derived by running all 17 apps rather than assumed. Every app
returned 0 for both ``main(["--agentic"])`` and ``main(["--", "--agentic"])``,
and every pair of outputs was byte-identical.

Usage::

    class TestWifiSeparatorCLI(SeparatorContractMixin, unittest.TestCase):
        MODULE_PATH = "wifi.cli"
        APP_ID = "wifi"
"""

from __future__ import annotations

import contextlib
import importlib
import io


class SeparatorContractMixin:
    """Contract tests verifying a CLIApp-based app honours the ``--`` separator guarantee.

    Subclasses must set :attr:`MODULE_PATH` and :attr:`APP_ID`, and must also
    inherit from ``unittest.TestCase``.

    The contract is a regression guard: all 17 CLIApp-based apps pass it at
    the time of writing. A failure means an app-level change broke separator
    stripping — either by pre-processing ``sys.argv`` before
    ``CLIApp.normalize_argv`` runs, or by bypassing ``run_with_assistant``.
    """

    #: Importable module exposing ``main(argv)``, e.g. ``"wifi.cli"``.
    MODULE_PATH: str
    #: Identifier the capsule announces itself with. Not always the package
    #: name — ``calendars`` emits ``agentic: calendar`` (singular).
    APP_ID: str

    def _run(self, argv: list[str]) -> tuple[int, str]:
        """Invoke ``main(argv)`` and return ``(rc, stdout)``."""
        module = importlib.import_module(self.MODULE_PATH)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.main(argv)
        return rc, buf.getvalue()

    def test_agentic_without_separator_returns_zero(self):
        """Baseline: ``main(["--agentic"])`` exits 0 and names the app."""
        rc, out = self._run(["--agentic"])
        self.assertEqual(rc, 0)
        self.assertIn(f"agentic: {self.APP_ID}", out)

    def test_agentic_with_separator_returns_zero(self):
        """``main(["--", "--agentic"])`` exits 0 after stripping the ``--``."""
        rc, out = self._run(["--", "--agentic"])
        self.assertEqual(
            rc,
            0,
            "separator form returned non-zero; normalize_argv may not be applied",
        )
        self.assertIn(f"agentic: {self.APP_ID}", out)

    def test_separator_form_output_is_byte_identical(self):
        """Stripping the separator must produce exactly the same output.

        Guards the failure mode where the separator is stripped but something
        downstream (a log line, a startup message) differs between the two
        forms. If the outputs diverge, the ``--`` was not fully transparent.
        """
        _, out_plain = self._run(["--agentic"])
        _, out_sep = self._run(["--", "--agentic"])
        # Compared as UTF-8 bytes, matching the wording of this contract and
        # the byte-count assertions in tests/agentic_cli_contract.py. Several
        # capsules carry non-ASCII (calendars uses em dashes and arrows), so
        # len(str) and the byte length genuinely differ.
        plain_bytes = out_plain.encode("utf-8")
        sep_bytes = out_sep.encode("utf-8")
        self.assertEqual(
            plain_bytes,
            sep_bytes,
            f"separator form differs: plain={len(plain_bytes)} bytes, "
            f"sep={len(sep_bytes)} bytes",
        )
