"""CLI separator contract for the telemetry domain.

Also pins the single-normalization invariant. telemetry is the one app that
normalizes argv in its own ``main()`` — it has to, because the ``otel``
passthrough intercepts on ``argv[0]`` and a leading bare ``--`` would hide the
subcommand. That makes double-normalization a live hazard here in a way it is
not for the other 17 apps.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.cli_separator_contract import SeparatorContractMixin


class TestTelemetrySeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    MODULE_PATH = "telemetry.cli_sessions"
    APP_ID = "telemetry"


class TestTelemetryArgvNormalizedOnce(unittest.TestCase):
    """``main()`` must hand RAW argv to ``run_with_assistant``.

    ``normalize_argv`` is deliberately not idempotent: it strips the *first*
    bare ``--`` on every call. ``run_with_assistant`` normalizes internally, so
    a ``main()`` that also normalizes strips two separators and eats a later
    ``--`` that POSIX end-of-options requires be preserved. Measured before the
    fix::

        ["sessions", "--", "--", "x"]
          -> normalize once  ["sessions", "--", "x"]
          -> normalize twice ["sessions", "x"]        # second -- lost

    Asserting on what reaches ``run_with_assistant`` rather than on the parsed
    result: the double strip is invisible downstream once argparse has consumed
    the tokens, so a behavioural assertion would not localise the defect.
    """

    def test_second_separator_survives_to_run_with_assistant(self):
        import telemetry.cli_sessions as cs

        with mock.patch.object(cs.app, "run_with_assistant", return_value=0) as spy:
            cs.main(["sessions", "--", "--", "x"])

        passed = list(spy.call_args.kwargs["argv"])
        self.assertEqual(
            passed,
            ["sessions", "--", "--", "x"],
            "main() must not pre-normalize; run_with_assistant normalizes once itself",
        )

    def test_otel_passthrough_still_strips_the_leading_separator(self):
        """``telemetry -- otel ...`` must still route to the otel CLI.

        The otel branch normalizes a probe copy precisely so a leading bare
        ``--`` cannot hide ``otel`` in position 0. Removing the pre-normalization
        from the main path must not regress that.
        """
        import telemetry.cli_sessions as cs

        with mock.patch("telemetry.otel.cli.main", return_value=0) as otel_main:
            cs.main(["--", "otel", "query", "--format", "json"])

        otel_main.assert_called_once_with(["query", "--format", "json"])


if __name__ == "__main__":
    unittest.main()
