"""CLI separator contract for the telemetry domain."""
from __future__ import annotations

import unittest

from tests.cli_separator_contract import SeparatorContractMixin


class TestTelemetrySeparatorCLI(SeparatorContractMixin, unittest.TestCase):
    MODULE_PATH = "telemetry.cli_sessions"
    APP_ID = "telemetry"
