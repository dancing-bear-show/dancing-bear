"""Tests for apple_music agentic capsule and CLI contract.

apple_music is minimal-tier: it defines ``build_agentic_capsule`` and
``emit_agentic_context`` but no ``build_domain_map`` and no CLI tree (the
charts/worker pattern), so both ``EXPECT_DOMAIN_MAP`` and ``EXPECT_CLI_TREE``
are False. The mixin then asserts ``build_domain_map`` is genuinely absent
rather than merely skipping the domain-map tests.

Only the capsule's command list is asserted here — everything else is the
shared contract's job. The ``--`` separator contract is adopted in
``tests/apple_music_tests/cli/test_apple_music_cli.py`` rather than here, so
this app declares it exactly once.
"""

from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestAppleMusicAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "apple_music.agentic"
    APP_ID = "apple-music-assistant"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestAppleMusicCapsuleContent(unittest.TestCase):
    """Capsule content specific to apple_music, not covered by any contract."""

    def test_capsule_mentions_key_commands(self):
        import apple_music.agentic as m

        capsule = m.build_agentic_capsule()
        for cmd in ("ping", "list", "export", "create", "dedupe", "token"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, capsule)


class TestAppleMusicAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """CLI-level --agentic contract for apple-music-assistant."""

    MODULE_PATH = "apple_music.__main__"
    APP_ID = "apple-music-assistant"


if __name__ == "__main__":
    unittest.main()
