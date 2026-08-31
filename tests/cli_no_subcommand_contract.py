"""Shared contract for no-subcommand behaviour (rule A7).

Unlike the other CLI contracts, this one does **not** assert a uniform value.
Two apps deliberately differ from the help+0 majority, and that divergence is
the point: A7 says the no-subcommand exit code must be *chosen*, not accidental.
A contract that forced them all to agree would break two public CLI surfaces.

So each adopter declares what it expects, and the contract pins it. The value is
regression detection, not uniformity: ``worker`` exits 1 and ``workflow`` exits 2
on purpose, and a refactor that quietly normalised either to 0 would break a
documented interface with nothing to catch it.

Until this contract existed, A7 was the one rule in ``.llm/CLI_STANDARD.md`` with
no test behind it, which is why it was marked SHOULD rather than MUST.

Usage::

    class TestWifiNoSubcommand(NoSubcommandContractMixin, unittest.TestCase):
        MODULE_PATH = "wifi.cli"
        EXPECTED_RC = 0
        EXPECTED_STREAM = "stdout"

Measured across all 18 apps (rc / stream):

    rc=0, stdout   the other 16 apps -- full help, framework default
    rc=1, stderr   worker    -- one-line usage; see worker.cli._no_command_usage()
    rc=2, stderr   workflow  -- one-line usage; same pattern

``charts`` (was 1) and ``telemetry`` (was 2) were normalised to help+0 when this
contract was written. Neither had a stated rationale -- charts was a bare
``return 1`` predating the src/ move (#147), and telemetry's 2 was incidental to
Click, carried through the argparse port without anyone choosing it. worker and
workflow keep theirs because both carry a docstring explaining the choice, which
is exactly the distinction A7 asks for.

Two things a naive version of this contract would miss:

- **The stream matters as much as the code.** worker and workflow print a
  one-line usage to *stderr*; everything else prints full help to *stdout*. An
  exit-code-only assertion cannot tell those apart -- verified by probe: moving
  worker's usage to stdout fails here with ``'stdout' != 'stderr'`` while its
  exit code stays 1.
- **Every app must produce output.** A silent exit is a usability bug whatever
  the code says, so the contract asserts *something* was written.
"""

from __future__ import annotations

import contextlib
import importlib
import io


class NoSubcommandContractMixin:
    """Contract tests for rule A7 — deliberate no-subcommand behaviour.

    Subclasses must set :attr:`MODULE_PATH`, :attr:`EXPECTED_RC` and
    :attr:`EXPECTED_STREAM`, and must also inherit from ``unittest.TestCase``.
    """

    #: Importable module exposing ``main(argv)``, e.g. ``"wifi.cli"``.
    MODULE_PATH: str
    #: Exit code this app returns for a bare invocation. Declared per app
    #: rather than defaulted, so adopting the contract forces a decision
    #: instead of silently inheriting someone else's.
    EXPECTED_RC: int
    #: Which stream carries the output: ``"stdout"`` or ``"stderr"``.
    #: An app writing to BOTH resolves to ``"both"`` and fails against
    #: either single-stream expectation — stray stderr is a real finding,
    #: not a detail to round away.
    EXPECTED_STREAM: str

    def _run_bare(self) -> tuple[object, str, str]:
        """Invoke ``main([])`` and capture both streams."""
        module = importlib.import_module(self.MODULE_PATH)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = module.main([])
            except SystemExit as exc:  # NOSONAR S5754 - observing the exit code IS the contract
                # argparse exits instead of returning; a bare `raise` here
                # would defeat the assertion this helper exists to make.
                rc = exc.code if exc.code is not None else 0
        return rc, out.getvalue(), err.getvalue()

    def test_bare_invocation_returns_the_declared_exit_code(self):
        """The exit code is a public interface; pin the chosen value."""
        rc, _out, _err = self._run_bare()
        self.assertEqual(
            rc,
            self.EXPECTED_RC,
            f"{self.MODULE_PATH} bare invocation returned {rc}, "
            f"expected {self.EXPECTED_RC} (rule A7 — this value is deliberate)",
        )

    def test_bare_invocation_writes_to_the_declared_stream(self):
        """help-on-stdout and usage-on-stderr are different interfaces.

        An exit-code assertion alone cannot distinguish them, so a refactor
        could move a message between streams without any test noticing.
        """
        _rc, out, err = self._run_bare()
        # "both" is its own answer, not a tie broken in stdout's favour. An
        # `if out: "stdout"` check passes an app that ALSO leaked a warning or
        # a log line to stderr, which is precisely the accidental output this
        # assertion exists to catch.
        if out and err:
            written = "both"
        elif out:
            written = "stdout"
        elif err:
            written = "stderr"
        else:
            written = "none"
        self.assertEqual(
            written,
            self.EXPECTED_STREAM,
            f"{self.MODULE_PATH} wrote to {written}, expected {self.EXPECTED_STREAM}"
            + (f"\n  stray stderr: {err.strip()[:200]!r}" if written == "both" else ""),
        )

    def test_bare_invocation_is_not_silent(self):
        """A bare invocation must tell the user something.

        Asserted separately from the stream check because a silent exit is a
        usability failure on its own terms, whatever the exit code says.
        """
        _rc, out, err = self._run_bare()
        self.assertTrue(
            (out + err).strip(),
            f"{self.MODULE_PATH} produced no output at all on a bare invocation",
        )
