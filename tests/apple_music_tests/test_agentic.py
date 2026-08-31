"""Tests for apple_music agentic capsule and CLI contract.

The builder contract mixin (AgenticBuilderContractMixin) includes
build_domain_map() assertions that apple_music does not implement —
it is minimal-tier (charts pattern: capsule + emit only). Direct tests
are written here instead. Once the EXPECT_DOMAIN_MAP opt-out flag lands
on the shared mixin, this suite should adopt it.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from tests.agentic_cli_contract import AgenticCLIContractMixin


class TestAppleMusicAgenticBuilder(unittest.TestCase):
    """Direct tests for apple_music.agentic builder functions."""

    def _module(self):
        import apple_music.agentic as m
        return m

    def test_capsule_is_a_nonempty_string(self):
        capsule = self._module().build_agentic_capsule()
        self.assertIsInstance(capsule, str)
        self.assertGreater(len(capsule.strip()), 0)

    def test_capsule_announces_the_app_id(self):
        capsule = self._module().build_agentic_capsule()
        self.assertEqual(capsule.splitlines()[0].strip(), "agentic: apple-music-assistant")

    def test_capsule_declares_purpose(self):
        capsule = self._module().build_agentic_capsule()
        self.assertIn("purpose:", capsule)

    def test_capsule_mentions_key_commands(self):
        capsule = self._module().build_agentic_capsule()
        for cmd in ("ping", "list", "export", "create", "dedupe", "token"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, capsule)

    def test_capsule_is_substantial(self):
        capsule = self._module().build_agentic_capsule()
        self.assertGreater(len(capsule.encode("utf-8")), 200)

    def test_emit_returns_zero_and_writes_capsule(self):
        module = self._module()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.emit_agentic_context()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: apple-music-assistant", buf.getvalue())

    def test_emit_output_matches_builder(self):
        module = self._module()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.emit_agentic_context()
        self.assertEqual(buf.getvalue().strip(), module.build_agentic_capsule().strip())

    def test_emit_accepts_fmt_and_compact_positionally(self):
        module = self._module()
        for args in ((), ("yaml",), ("text", True)):
            with self.subTest(args=args):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = module.emit_agentic_context(*args)
                self.assertEqual(rc, 0)


class TestAppleMusicAgenticCLI(AgenticCLIContractMixin, unittest.TestCase):
    """CLI-level --agentic contract for apple-music-assistant."""

    MODULE_PATH = "apple_music.__main__"
    APP_ID = "apple-music-assistant"


if __name__ == "__main__":
    unittest.main()
