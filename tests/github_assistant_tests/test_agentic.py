"""Contract coverage for github_assistant's agentic surface.

Two contracts, same reason: catch the two swallowed-import failure modes.
The builder contract exercises ``github_assistant/agentic.py`` directly; the
CLI contract exercises ``main(["--agentic"])`` end-to-end, where a broken
capsule degrades to a 200B stub the ``rc=0`` check alone would not notice.
"""

from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestGithubAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """Shared per-domain builder contract."""

    MODULE_PATH = "github_assistant.agentic"
    APP_ID = "github"


class TestGithubAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """Shared CLI-level --agentic contract."""

    MODULE_PATH = "github_assistant.cli"
    APP_ID = "github"


if __name__ == "__main__":
    unittest.main()
