"""Tests for mail/agentic.py -- compact mode, domain map helpers, error paths."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import capture_stdout


class TestMailBuildAgenticCapsuleCompact(unittest.TestCase):
    """build_agentic_capsule(compact=True) skips .llm context files and flows index."""

    def test_compact_returns_string(self):
        import mail.agentic as mod
        self.assertIsInstance(mod.build_agentic_capsule(compact=True), str)

    def test_compact_contains_app_id(self):
        import mail.agentic as mod
        self.assertIn("agentic: mail", mod.build_agentic_capsule(compact=True))

    def test_compact_contains_core_commands(self):
        import mail.agentic as mod
        result = mod.build_agentic_capsule(compact=True)
        self.assertIn("labels export", result)
        self.assertIn("messages search", result)

    def test_compact_never_longer_than_full(self):
        """Compact mode always has <= bytes vs full mode (it skips file sections)."""
        import mail.agentic as mod
        compact = mod.build_agentic_capsule(compact=True)
        full = mod.build_agentic_capsule(compact=False)
        self.assertLessEqual(len(compact), len(full))

    def test_full_mode_returns_string(self):
        import mail.agentic as mod
        result = mod.build_agentic_capsule(compact=False)
        self.assertIsInstance(result, str)
        self.assertIn("agentic: mail", result)


class TestMailEmitAgenticContext(unittest.TestCase):
    """emit_agentic_context() compact and format variants."""

    def test_emit_default_returns_zero(self):
        import mail.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_compact_returns_zero(self):
        import mail.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context(compact=True)
        self.assertEqual(rc, 0)

    def test_emit_fmt_yaml_returns_zero(self):
        import mail.agentic as mod
        with capture_stdout():
            rc = mod.emit_agentic_context(_fmt="yaml")
        self.assertEqual(rc, 0)

    def test_emit_output_contains_header(self):
        import mail.agentic as mod
        with capture_stdout() as buf:
            mod.emit_agentic_context()
        self.assertIn("agentic: mail", buf.getvalue())

    def test_emit_compact_output_contains_header(self):
        import mail.agentic as mod
        with capture_stdout() as buf:
            mod.emit_agentic_context(compact=True)
        self.assertIn("agentic: mail", buf.getvalue())


class TestMailGetParserFallback(unittest.TestCase):
    """_get_parser returns None when CLI import raises."""

    def test_build_cli_tree_handles_none_parser(self):
        """_build_cli_tree returns empty string when _get_parser returns None."""
        import mail.agentic as mod
        with patch.object(mod, "_get_parser", return_value=None):
            result = mod._build_cli_tree()
        self.assertEqual(result, "")

    def test_cli_path_exists_returns_false_for_none_parser(self):
        """_cli_path_exists returns False when _get_parser returns None."""
        import mail.agentic as mod
        with patch.object(mod, "_get_parser", return_value=None):
            result = mod._cli_path_exists(["labels", "sync"])
        self.assertFalse(result)


class TestMailBinExists(unittest.TestCase):
    """_bin_exists() truth values and exception handling."""

    def test_returns_true_when_file_exists(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            # _bin_exists looks for bin/<name> relative to cwd
            bin_dir = Path(td) / "bin"
            bin_dir.mkdir()
            (bin_dir / "phone").touch()
            with patch("mail.agentic.os.getcwd", return_value=td):
                self.assertTrue(mod._bin_exists("phone"))

    def test_returns_false_when_file_missing(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            with patch("mail.agentic.os.getcwd", return_value=td):
                self.assertFalse(mod._bin_exists("nonexistent-binary"))

    def test_returns_false_on_os_error(self):
        import mail.agentic as mod
        with patch("mail.agentic.os.getcwd", side_effect=OSError("no cwd")):
            self.assertFalse(mod._bin_exists("phone"))


class TestMailListFolderModules(unittest.TestCase):
    """_list_folder_modules() with various folder configurations."""

    def test_returns_empty_for_nonexistent_folder(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            result = mod._list_folder_modules(Path(td), "no_such_folder")
        self.assertEqual(result, [])

    def test_returns_name_docstring_pairs(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "main.py").write_text('"""Main CLI module."""\n', encoding="utf-8")
            result = mod._list_folder_modules(Path(td), "cli")
        self.assertEqual(len(result), 1)
        name, doc = result[0]
        self.assertEqual(name, "cli/main.py")
        self.assertEqual(doc, "Main CLI module.")

    def test_extracts_first_docstring_line_only(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "mod.py").write_text(
                '"""First line.\n\nSecond paragraph."""\n', encoding="utf-8"
            )
            result = mod._list_folder_modules(Path(td), "cli")
        _, doc = result[0]
        self.assertEqual(doc, "First line.")

    def test_handles_unparseable_file_gracefully(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "broken.py").write_text("def (syntax error", encoding="utf-8")
            result = mod._list_folder_modules(Path(td), "cli")
        self.assertEqual(len(result), 1)
        name, doc = result[0]
        self.assertEqual(name, "cli/broken.py")
        self.assertEqual(doc, "")

    def test_skips_non_py_files(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "notes.txt").write_text("docs", encoding="utf-8")
            result = mod._list_folder_modules(Path(td), "cli")
        self.assertEqual(result, [])

    def test_no_docstring_returns_empty_doc(self):
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "nodoc.py").write_text("x = 1\n", encoding="utf-8")
            result = mod._list_folder_modules(Path(td), "cli")
        self.assertEqual(len(result), 1)
        _, doc = result[0]
        self.assertEqual(doc, "")


class TestMailBuildDomainMap(unittest.TestCase):
    """build_domain_map() generates full map including key modules and folder sections."""

    def test_returns_string(self):
        import mail.agentic as mod
        self.assertIsInstance(mod.build_domain_map(), str)

    def test_contains_top_level_entry(self):
        import mail.agentic as mod
        self.assertIn("Top-Level", mod.build_domain_map())

    def test_key_modules_section_when_files_exist(self):
        """build_domain_map includes Key Modules when a key file is found in cwd."""
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "agentic.py").touch()
            with patch("mail.agentic.os.getcwd", return_value=td):
                result = mod.build_domain_map()
        self.assertIn("Key Modules", result)
        self.assertIn("agentic.py", result)

    def test_cli_modules_section_when_cli_folder_has_py_files(self):
        """build_domain_map includes CLI Modules when cli/ folder has .py files."""
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir()
            (cli_dir / "dispatch.py").write_text('"""Dispatch module."""\n', encoding="utf-8")
            with patch("mail.agentic.os.getcwd", return_value=td):
                result = mod.build_domain_map()
        self.assertIn("CLI Modules", result)
        self.assertIn("cli/dispatch.py", result)

    def test_binaries_section_when_bin_folder_exists(self):
        """build_domain_map includes Binaries when bin/ folder has files."""
        import mail.agentic as mod
        with tempfile.TemporaryDirectory() as td:
            bin_dir = Path(td) / "bin"
            bin_dir.mkdir()
            (bin_dir / "mail-assistant").touch()
            with patch("mail.agentic.os.getcwd", return_value=td):
                result = mod.build_domain_map()
        self.assertIn("Binaries", result)
        self.assertIn("mail-assistant", result)


class TestMailBuildFlows(unittest.TestCase):
    """build_flows() phone-conditional behavior."""

    def test_build_flows_returns_list(self):
        import mail.agentic as mod
        self.assertIsInstance(mod.build_flows(), list)

    def test_without_phone_binary_excludes_ios_flows(self):
        import mail.agentic as mod
        with patch.object(mod, "_bin_exists", return_value=False):
            result = mod.build_flows()
        ids = [f["id"] for f in result]
        self.assertTrue(all("ios" not in fid for fid in ids))

    def test_with_phone_binary_includes_ios_flows(self):
        import mail.agentic as mod
        with patch.object(mod, "_bin_exists", return_value=True):
            result = mod.build_flows()
        ids = [f["id"] for f in result]
        self.assertTrue(any("ios" in fid for fid in ids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
