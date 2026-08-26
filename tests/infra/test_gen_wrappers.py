"""Tests for bin/_gen_wrappers.py wrapper generator."""

import stat
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import bin_path, repo_root


class TestGenWrappers(unittest.TestCase):
    """Tests for the wrapper generator script."""

    def test_check_mode_no_changes(self):
        """Verify --check returns 0 when wrappers are in sync."""
        import subprocess  # nosec B404
        import sys

        proc = subprocess.run(  # nosec B603 - test uses trusted local script
            [sys.executable, str(bin_path("_gen_wrappers.py")), "--check"],
            capture_output=True,
            text=True,
            cwd=str(repo_root()),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("0 changed", proc.stdout)

    def test_verbose_lists_all_wrappers(self):
        """Verify --verbose shows unchanged files."""
        import subprocess  # nosec B404
        import sys

        proc = subprocess.run(  # nosec B603 - test uses trusted local script
            [sys.executable, str(bin_path("_gen_wrappers.py")), "--check", "--verbose"],
            capture_output=True,
            text=True,
            cwd=str(repo_root()),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Unchanged: mail", proc.stdout)
        self.assertIn("Unchanged: phone", proc.stdout)


class TestGenerateRouter(unittest.TestCase):
    """Tests for router generation."""

    def test_generate_router_standard_module(self):
        """Router contains the non-dotted dispatch branch for standard modules."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import generate_router

        content = generate_router({"mail": "mail"})
        self.assertIn("#!/usr/bin/env python3", content)
        self.assertIn('"mail": "mail"', content)
        # Router uses __main__ import for non-dotted modules
        self.assertIn("__main__", content)
        self.assertIn("raise SystemExit(_main())", content)

    def test_generate_router_core_module(self):
        """Router contains the dotted dispatch branch for core.* modules."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import generate_router

        content = generate_router({"assistant": "core.assistant_cli"})
        self.assertIn('"assistant": "core.assistant_cli"', content)
        # Router handles dotted modules via the '.' in module check
        self.assertIn('if "." in module:', content)


class TestRenderQltyConfig(unittest.TestCase):
    """Tests for the generated wrapper-symlink block in .qlty/qlty.toml."""

    BARE = 'exclude_patterns = [\n  "**/.venv/**",\n]\n\n[smells]\n'

    def _render(self, existing, names):
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import render_qlty_config

        return render_qlty_config(existing, names)

    def test_inserts_block_when_markers_absent(self):
        """A config with no markers gets the block before exclude_patterns' close."""
        result = self._render(self.BARE, ["mail", "charts"])
        self.assertIn("BEGIN GENERATED WRAPPER SYMLINKS", result)
        self.assertIn('"bin/mail",', result)
        self.assertIn('"bin/charts",', result)
        # Block lands inside the list, not after it.
        self.assertLess(result.index('"bin/mail",'), result.index("[smells]"))

    def test_names_sorted_for_stable_diffs(self):
        """Wrapper names are emitted sorted, so config order does not churn."""
        result = self._render(self.BARE, ["workflow", "assistant", "mail"])
        self.assertLess(result.index('"bin/assistant",'), result.index('"bin/mail",'))
        self.assertLess(result.index('"bin/mail",'), result.index('"bin/workflow",'))

    def test_regenerating_is_idempotent(self):
        """Rendering twice over its own output changes nothing."""
        once = self._render(self.BARE, ["mail", "charts"])
        twice = self._render(once, ["mail", "charts"])
        self.assertEqual(once, twice)

    def test_replaces_stale_block_without_duplicating(self):
        """A removed wrapper drops out; the block is replaced, not appended."""
        stale = self._render(self.BARE, ["mail", "charts"])
        fresh = self._render(stale, ["mail"])
        self.assertIn('"bin/mail",', fresh)
        self.assertNotIn('"bin/charts",', fresh)
        self.assertEqual(fresh.count("BEGIN GENERATED WRAPPER SYMLINKS"), 1)

    def test_router_itself_is_never_excluded(self):
        """_router.py is the one real file and must stay linted."""
        result = self._render(self.BARE, ["mail", "charts"])
        self.assertNotIn('"bin/_router.py"', result)

    def test_raises_when_exclude_patterns_missing(self):
        """A config without exclude_patterns fails loudly rather than silently."""
        with self.assertRaises(SystemExit):
            self._render("[smells]\nmode = \"comment\"\n", ["mail"])

    def test_live_config_matches_wrappers_yaml(self):
        """The committed qlty.toml lists exactly the generated wrapper symlinks."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import load_config

        config = load_config()
        text = (repo_root() / ".qlty" / "qlty.toml").read_text()
        for name in config.get("python", {}):
            self.assertIn(f'"bin/{name}",', text)


class TestLoadConfig(unittest.TestCase):
    """Tests for config loading."""

    def test_load_config_has_python_section(self):
        """Verify config loads with python section."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import load_config

        config = load_config()
        self.assertIn("python", config)
        self.assertIn("mail", config["python"])
        self.assertIn("phone", config["python"])

    def test_load_config_no_bash_section(self):
        """Verify bash section was removed (shortcuts deleted)."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import load_config

        config = load_config()
        # bash section should be empty or not present after cleanup
        bash = config.get("bash", {})
        self.assertEqual(len(bash), 0)


class TestUpdateFile(unittest.TestCase):
    """Tests for file update logic."""

    def test_update_file_creates_new(self):
        """Test creating a new file."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import _update_file

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "newfile"
            status = _update_file(path, "content", check=False)
            self.assertEqual(status, "created")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), "content")
            # Check executable
            mode = path.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)

    def test_update_file_unchanged(self):
        """Test file unchanged when content matches."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import _update_file

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "existing"
            path.write_text("same content")
            status = _update_file(path, "same content", check=False)
            self.assertEqual(status, "unchanged")

    def test_update_file_changed(self):
        """Test file updated when content differs."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import _update_file

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "existing"
            path.write_text("old content")
            status = _update_file(path, "new content", check=False)
            self.assertEqual(status, "changed")
            self.assertEqual(path.read_text(), "new content")

    def test_update_file_check_mode_no_write(self):
        """Test check mode doesn't write files."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import _update_file

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "newfile"
            status = _update_file(path, "content", check=True)
            self.assertEqual(status, "created")
            self.assertFalse(path.exists())


class TestParseSimpleYaml(unittest.TestCase):
    """Tests for the fallback YAML parser."""

    def test_parse_python_entries(self):
        """Test parsing python entries."""
        import sys
        sys.path.insert(0, str(repo_root() / "bin"))
        from _gen_wrappers import _parse_simple_yaml

        yaml_text = """
python:
  mail: {module: mail, doc: "Mail CLI."}
  phone: {module: phone, doc: "Phone CLI."}

manual:
  - llm
  - setup_venv
"""
        result = _parse_simple_yaml(yaml_text)
        self.assertIn("python", result)
        self.assertEqual(result["python"]["mail"]["module"], "mail")
        self.assertEqual(result["python"]["phone"]["doc"], "Phone CLI.")
        self.assertIn("llm", result["manual"])
        self.assertIn("setup_venv", result["manual"])


class TestWrappersExist(unittest.TestCase):
    """Verify expected wrappers exist in bin/."""

    def test_primary_wrappers_exist(self):
        """Test that primary Python wrappers exist."""
        for name in ["mail", "phone", "calendar", "schedule", "whatsapp", "wifi", "maker", "assistant"]:
            path = bin_path(name)
            self.assertTrue(path.exists(), f"Missing wrapper: {name}")

    def test_legacy_aliases_exist(self):
        """Test that legacy -assistant aliases exist."""
        for name in ["mail-assistant", "phone-assistant", "calendar-assistant", "schedule-assistant", "wifi-assistant"]:
            path = bin_path(name)
            self.assertTrue(path.exists(), f"Missing legacy alias: {name}")

    def test_bash_shortcuts_removed(self):
        """Verify bash shortcuts were removed."""
        removed = [
            "gmail-auth", "gmail-filters-export", "outlook-rules-sync",
            "ios-plan", "ios-analyze", "outlook-auth-device-code"
        ]
        for name in removed:
            path = bin_path(name)
            self.assertFalse(path.exists(), f"Bash shortcut should be removed: {name}")


if __name__ == "__main__":
    unittest.main()
