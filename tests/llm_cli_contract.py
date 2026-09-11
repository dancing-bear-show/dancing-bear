"""Shared contract-test mixin for domain LLM CLI modules.

Every domain built on ``core.llm_cli.make_domain_llm_module`` (or
``make_app_llm_config`` / ``LlmConfig``) satisfies the same public contract.
Subclass this mixin together with ``unittest.TestCase`` and supply the class
attributes to get the full contract suite for free.

Usage::

    class TestMyDomainLLMCLI(LLMCLIContractMixin, unittest.TestCase):
        MODULE_PATH = "mydomain.llm_cli"
        APP_ID = "mydomain"
        DOC_SUFFIX = "MYDOMAIN"
        EXPECTED_PROG = "llm-mydomain"
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

from tests.fixtures import capture_stdout


class LLMCLIContractMixin:
    """Contract tests for any domain built on core.llm_cli.make_domain_llm_module.

    Subclasses must set:
        MODULE_PATH   - importlib path, e.g. "wifi.llm_cli"
        APP_ID        - the app identifier emitted in agentic output, e.g. "wifi"
        DOC_SUFFIX    - the suffix used in generated filenames, e.g. "WIFI"
        EXPECTED_PROG - the value of CONFIG.prog, e.g. "llm-wifi"
    """

    MODULE_PATH: str
    APP_ID: str
    DOC_SUFFIX: str
    EXPECTED_PROG: str

    def _mod(self):
        return importlib.import_module(self.MODULE_PATH)

    # ------------------------------------------------------------------
    # main() contract — agentic
    # ------------------------------------------------------------------

    def test_agentic_stdout_returns_zero(self):
        mod = self._mod()
        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        self.assertEqual(rc, 0)
        self.assertIn(f"agentic: {self.APP_ID}", buf.getvalue())

    def test_help_raises_system_exit_zero(self):
        mod = self._mod()
        with self.assertRaises(SystemExit) as ctx:
            mod.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    # ------------------------------------------------------------------
    # main() contract — derive-all
    # ------------------------------------------------------------------

    def test_derive_all_outputs_files(self):
        mod = self._mod()
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(
                ["derive-all", "--out-dir", td, "--include-generated", "--stdout"]
            )
            self.assertEqual(rc, 0)
            agentic_file = Path(td) / f"AGENTIC_{self.DOC_SUFFIX}.md"
            domain_map_file = Path(td) / f"DOMAIN_MAP_{self.DOC_SUFFIX}.md"
            self.assertTrue(agentic_file.exists(), f"{agentic_file.name} not found")
            self.assertTrue(
                domain_map_file.exists(), f"{domain_map_file.name} not found"
            )
            self.assertIn(
                f"agentic: {self.APP_ID}",
                agentic_file.read_text(encoding="utf-8"),
            )
            # Shared repo-level files must NOT be written by domain derive-all.
            # Writing them would clobber .llm/familiarize.yaml, INVENTORY.md,
            # and PR_POLICIES.yaml that the repo-level generator owns.
            td_path = Path(td)
            self.assertFalse(
                (td_path / "INVENTORY.md").exists(),
                "domain derive-all must not write INVENTORY.md (repo-level file)",
            )
            self.assertFalse(
                (td_path / "familiarize.yaml").exists(),
                "domain derive-all must not write familiarize.yaml (repo-level file)",
            )
            self.assertFalse(
                (td_path / "PR_POLICIES.yaml").exists(),
                "domain derive-all must not write PR_POLICIES.yaml (repo-level file)",
            )

    def test_derive_all_subcommands_still_work(self):
        """inventory, familiar, policies emit their CONFIG builder, not a fallback.

        Suppressing the derive-all file write for these three must not detach
        their builders. Asserting only that output is non-empty does not catch
        that: every emit handler passes a non-empty fallback to _safe_call
        ("# LLM Agent Inventory\n\n(no data)", _default_policies(), and a
        familiar meta stub), so a detached builder still prints something.
        Verified by setting inventory=None on the domain factory — the
        subcommand degraded to the "(no data)" stub while a length-only
        assertion stayed green. Compare against the builder instead.
        """
        mod = self._mod()
        # familiar without --verbose resolves to familiar_compact.
        expected_builders = {
            "inventory": mod.CONFIG.inventory,
            "familiar": mod.CONFIG.familiar_compact,
            "policies": mod.CONFIG.policies,
        }
        for subcmd, builder in expected_builders.items():
            with self.subTest(subcmd=subcmd):
                with capture_stdout() as buf:
                    rc = mod.main([subcmd, "--stdout"])
                self.assertEqual(rc, 0, f"{subcmd} --stdout returned non-zero")
                self.assertIsNotNone(
                    builder, f"{subcmd} builder is not wired on CONFIG"
                )
                self.assertEqual(
                    buf.getvalue(),
                    builder() + "\n",
                    f"{subcmd} --stdout did not emit its configured builder",
                )

    # ------------------------------------------------------------------
    # main() contract — other subcommands
    # ------------------------------------------------------------------

    def test_domain_map_stdout_returns_zero(self):
        mod = self._mod()
        with capture_stdout():
            rc = mod.main(["domain-map", "--stdout"])
        self.assertEqual(rc, 0)

    def test_inventory_stdout_returns_zero(self):
        mod = self._mod()
        with capture_stdout():
            rc = mod.main(["inventory", "--stdout"])
        self.assertEqual(rc, 0)

    def test_familiar_stdout_returns_zero(self):
        mod = self._mod()
        with capture_stdout():
            rc = mod.main(["familiar", "--stdout"])
        self.assertEqual(rc, 0)

    def test_policies_stdout_returns_zero(self):
        mod = self._mod()
        with capture_stdout():
            rc = mod.main(["policies", "--stdout"])
        self.assertEqual(rc, 0)

    # ------------------------------------------------------------------
    # CONFIG contract
    # ------------------------------------------------------------------

    def test_config_prog(self):
        mod = self._mod()
        self.assertEqual(mod.CONFIG.prog, self.EXPECTED_PROG)

    def test_config_agentic_filename(self):
        mod = self._mod()
        self.assertEqual(
            mod.CONFIG.agentic_filename, f"AGENTIC_{self.DOC_SUFFIX}.md"
        )

    def test_config_domain_map_filename(self):
        mod = self._mod()
        self.assertEqual(
            mod.CONFIG.domain_map_filename, f"DOMAIN_MAP_{self.DOC_SUFFIX}.md"
        )

    def test_config_shared_filenames_are_none(self):
        """Domain configs must not set shared repo-level filenames."""
        mod = self._mod()
        self.assertIsNone(
            mod.CONFIG.inventory_filename,
            "inventory_filename must be None for domain modules",
        )
        self.assertIsNone(
            mod.CONFIG.familiar_filename,
            "familiar_filename must be None for domain modules",
        )
        self.assertIsNone(
            mod.CONFIG.policies_filename,
            "policies_filename must be None for domain modules",
        )

    def test_config_agentic_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.agentic()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)
        self.assertIn(self.APP_ID, result.lower())

    def test_config_domain_map_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.domain_map()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_config_inventory_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.inventory()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_config_familiar_compact_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.familiar_compact()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_config_familiar_extended_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.familiar_extended()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_config_policies_returns_nonempty_string(self):
        mod = self._mod()
        result = mod.CONFIG.policies()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    # ------------------------------------------------------------------
    # build_parser() contract
    # ------------------------------------------------------------------

    def test_build_parser_returns_parser_with_parse_args(self):
        mod = self._mod()
        parser = mod.build_parser()
        self.assertIsNotNone(parser)
        self.assertTrue(hasattr(parser, "parse_args"))
        help_text = parser.format_help()
        self.assertIn("agentic", help_text)
