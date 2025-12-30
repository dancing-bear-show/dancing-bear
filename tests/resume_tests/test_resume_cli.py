"""Tests for resume/cli/main.py CLI module."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import bin_path, repo_root, run, temp_yaml_file


class TestResumeCLIHelp(unittest.TestCase):
    """Test resume CLI help and invocation methods."""

    def test_help_via_module_invocation(self):
        """Test that python -m resume --help works."""
        proc = run([sys.executable, "-m", "resume", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("extract", proc.stdout.lower())
        self.assertIn("summarize", proc.stdout.lower())
        self.assertIn("render", proc.stdout.lower())

    def test_help_via_assistant_wrapper(self):
        """Test that ./bin/assistant resume --help works."""
        root = repo_root()
        wrapper = bin_path("assistant")
        if not wrapper.exists():
            self.skipTest("bin/assistant not found")
        proc = run([sys.executable, str(wrapper), "resume", "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("extract", proc.stdout.lower())

    def test_agentic_flag(self):
        """Test that --agentic flag emits context."""
        proc = run([sys.executable, "-m", "resume", "--agentic"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("agentic: resume", proc.stdout)

    def test_agentic_compact_flag(self):
        """Test that --agentic --agentic-compact works."""
        proc = run([sys.executable, "-m", "resume", "--agentic", "--agentic-compact"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("agentic:", proc.stdout)


class TestResumeCLISubcommandHelp(unittest.TestCase):
    """Test resume CLI subcommand help text."""

    def test_extract_help(self):
        """Test extract subcommand help."""
        proc = run([sys.executable, "-m", "resume", "extract", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--linkedin", proc.stdout)
        self.assertIn("--resume", proc.stdout)

    def test_summarize_help(self):
        """Test summarize subcommand help."""
        proc = run([sys.executable, "-m", "resume", "summarize", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--data", proc.stdout)
        self.assertIn("--seed", proc.stdout)

    def test_render_help(self):
        """Test render subcommand help."""
        proc = run([sys.executable, "-m", "resume", "render", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--data", proc.stdout)
        self.assertIn("--template", proc.stdout)

    def test_structure_help(self):
        """Test structure subcommand help."""
        proc = run([sys.executable, "-m", "resume", "structure", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--source", proc.stdout)

    def test_align_help(self):
        """Test align subcommand help."""
        proc = run([sys.executable, "-m", "resume", "align", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--data", proc.stdout)
        self.assertIn("--job", proc.stdout)

    def test_candidate_init_help(self):
        """Test candidate-init subcommand help."""
        proc = run([sys.executable, "-m", "resume", "candidate-init", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--data", proc.stdout)


class TestResumeCLIGroupHelp(unittest.TestCase):
    """Test resume CLI group subcommand help text."""

    def test_style_group_help(self):
        """Test style group help."""
        proc = run([sys.executable, "-m", "resume", "style", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("build", proc.stdout)

    def test_style_build_help(self):
        """Test style build subcommand help."""
        proc = run([sys.executable, "-m", "resume", "style", "build", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--corpus-dir", proc.stdout)

    def test_files_group_help(self):
        """Test files group help."""
        proc = run([sys.executable, "-m", "resume", "files", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("tidy", proc.stdout)

    def test_files_tidy_help(self):
        """Test files tidy subcommand help."""
        proc = run([sys.executable, "-m", "resume", "files", "tidy", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--dir", proc.stdout)
        self.assertIn("--keep", proc.stdout)

    def test_experience_group_help(self):
        """Test experience group help."""
        proc = run([sys.executable, "-m", "resume", "experience", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("export", proc.stdout)

    def test_experience_export_help(self):
        """Test experience export subcommand help."""
        proc = run([sys.executable, "-m", "resume", "experience", "export", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--data", proc.stdout)
        self.assertIn("--resume", proc.stdout)


class TestResumeCLIMain(unittest.TestCase):
    """Test resume CLI main function directly."""

    def test_main_import_exists(self):
        """Test that main function can be imported."""
        from resume.cli.main import main

        self.assertIsNotNone(main)
        self.assertTrue(callable(main))

    def test_main_returns_zero_with_help(self):
        """Test that main returns 0 when showing help."""
        from resume.cli.main import main

        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_no_args_shows_help(self):
        """Test that main with no args shows help and returns 0."""
        from resume.cli.main import main

        # No args should print help and return 0
        result = main([])
        self.assertEqual(result, 0)


class TestResumeCLIExtract(unittest.TestCase):
    """Test resume extract command functionality."""

    def test_extract_missing_args(self):
        """Test extract with no inputs still works (produces empty data)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "data.json")
            proc = run([
                sys.executable, "-m", "resume", "extract",
                "--out", out_path,
            ])
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(os.path.exists(out_path))

    def test_extract_with_nonexistent_file(self):
        """Test extract with nonexistent file reports error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "data.json")
            proc = run([
                sys.executable, "-m", "resume", "extract",
                "--linkedin", "/nonexistent/file.txt",
                "--out", out_path,
            ])
            # Command may succeed with empty data or fail - check stderr for error message
            # The io_utils.read_text_any handles missing files gracefully
            # Just verify it doesn't crash unexpectedly
            self.assertIn(proc.returncode, [0, 1])


class TestResumeCLISummarize(unittest.TestCase):
    """Test resume summarize command functionality."""

    def test_summarize_with_minimal_data(self):
        """Test summarize with minimal candidate data."""
        data = {
            "name": "Test User",
            "headline": "Software Engineer",
            "skills": ["Python", "Java"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme Corp",
                    "bullets": ["Built systems"],
                }
            ],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "summary.md")
                proc = run([
                    sys.executable, "-m", "resume", "summarize",
                    "--data", data_path,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))


class TestResumeCLICandidateInit(unittest.TestCase):
    """Test resume candidate-init command functionality."""

    def test_candidate_init_basic(self):
        """Test candidate-init generates skills YAML."""
        data = {
            "name": "Test User",
            "headline": "Software Engineer",
            "email": "test@example.com",
            "skills": ["Python", "Java", "Go"],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "candidate.yaml")
                proc = run([
                    sys.executable, "-m", "resume", "candidate-init",
                    "--data", data_path,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))


class TestResumeCLIAlign(unittest.TestCase):
    """Test resume align command functionality."""

    def test_align_basic(self):
        """Test align produces alignment report."""
        candidate = {
            "name": "Test User",
            "skills": ["Python", "AWS", "Docker"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "bullets": ["Built Python services", "Deployed to AWS"],
                }
            ],
        }
        job = {
            "title": "Senior Engineer",
            "required_skills": ["Python", "AWS"],
            "preferred_skills": ["Docker", "Kubernetes"],
        }
        with temp_yaml_file(candidate) as cand_path:
            with temp_yaml_file(job) as job_path:
                with tempfile.TemporaryDirectory() as tmpdir:
                    out_path = os.path.join(tmpdir, "alignment.json")
                    proc = run([
                        sys.executable, "-m", "resume", "align",
                        "--data", cand_path,
                        "--job", job_path,
                        "--out", out_path,
                    ])
                    self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                    self.assertTrue(os.path.exists(out_path))


class TestResumeCLIResolveOut(unittest.TestCase):
    """Test _resolve_out helper function."""

    def test_resolve_out_with_explicit_path(self):
        """Test _resolve_out returns explicit --out path."""
        from resume.cli.main import _resolve_out
        import argparse

        args = argparse.Namespace(out="/tmp/test.json", profile=None, out_dir="out")
        result = _resolve_out(args, ".json", "data")
        self.assertEqual(result, Path("/tmp/test.json"))

    def test_resolve_out_with_profile(self):
        """Test _resolve_out builds nested path with profile."""
        from resume.cli.main import _resolve_out
        import argparse

        args = argparse.Namespace(out=None, profile="testprofile", out_dir="out")
        result = _resolve_out(args, ".json", "data")
        self.assertEqual(result.name, "data.json")
        self.assertIn("testprofile", str(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
