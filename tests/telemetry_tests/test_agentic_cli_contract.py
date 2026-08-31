"""Agentic CLI contract for the telemetry domain."""
from __future__ import annotations

import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestTelemetryAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    MODULE_PATH = "telemetry.cli_sessions"
    APP_ID = "telemetry"
