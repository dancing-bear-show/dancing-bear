"""Tests for mail.llm_cli.

mail.llm_cli is a re-export shim that delegates to core.llm_cli — it does not
define a domain-specific CONFIG, derive-all filenames, or a domain prog. The
shared LLMCLIContractMixin therefore does not apply here.

Contract override rationale:
- No CONFIG: mail.llm_cli re-exports core functions; CONFIG lives in core.
- No domain derive-all files: mail/llm derive-all writes the repo-level docs,
  not AGENTIC_MAIL.md / DOMAIN_MAP_MAIL.md.
- build_parser requires a config argument (core-level function, not a no-arg
  domain entrypoint).

Tests here verify that the shim correctly delegates to the shared LLM CLI.
"""

import unittest

from tests.fixtures import capture_stdout


class TestMailLLMCLIShim(unittest.TestCase):
    """Smoke tests verifying the mail.llm_cli re-export shim delegates correctly."""

    def test_agentic_stdout_returns_zero(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: mail", buf.getvalue())

    def test_main_is_callable(self):
        import mail.llm_cli as mod

        self.assertTrue(callable(mod.main))

    def test_build_parser_is_callable(self):
        import mail.llm_cli as mod

        self.assertTrue(callable(mod.build_parser))

    def test_help_raises_system_exit_zero(self):
        import mail.llm_cli as mod

        with self.assertRaises(SystemExit) as ctx:
            mod.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
