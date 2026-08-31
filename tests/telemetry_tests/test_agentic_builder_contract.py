"""Agentic builder contract for the telemetry domain (minimal tier)."""
from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin


class TestTelemetryAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    MODULE_PATH = "telemetry.agentic"
    APP_ID = "telemetry"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False
