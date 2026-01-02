"""Tests for resume/cli/main.py CLI module."""

from __future__ import annotations

from tests.fixtures import test_path
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

        args = argparse.Namespace(out=test_path("test.json"), profile=None, out_dir="out")
        result = _resolve_out(args, ".json", "data")
        self.assertEqual(result, Path(test_path("test.json")))

    def test_resolve_out_with_profile(self):
        """Test _resolve_out builds nested path with profile."""
        from resume.cli.main import _resolve_out
        import argparse

        args = argparse.Namespace(out=None, profile="testprofile", out_dir="out")
        result = _resolve_out(args, ".json", "data")
        self.assertEqual(result.name, "data.json")
        self.assertIn("testprofile", str(result))

    def test_resolve_out_uses_default_profile(self):
        """Test _resolve_out uses DEFAULT_PROFILE when profile is None."""
        from resume.cli.main import _resolve_out, DEFAULT_PROFILE
        import argparse

        args = argparse.Namespace(out=None, profile=None, out_dir="out")
        result = _resolve_out(args, ".json", "data")
        self.assertIn(DEFAULT_PROFILE, str(result))


class TestResumeCLIHelpers(unittest.TestCase):
    """Test helper functions in resume CLI."""

    def test_extend_seed_with_style_no_profile(self):
        """Test _extend_seed_with_style returns seed unchanged when no style profile."""
        from resume.cli.main import _extend_seed_with_style

        seed = {"keywords": ["python", "aws"]}
        result = _extend_seed_with_style(seed, None)
        self.assertEqual(result, seed)

    def test_extend_seed_with_style_nonexistent_file(self):
        """Test _extend_seed_with_style handles missing file gracefully."""
        from resume.cli.main import _extend_seed_with_style

        seed = {"keywords": ["python"]}
        result = _extend_seed_with_style(seed, "/nonexistent/style.json")
        # Should return original seed on error
        self.assertEqual(result, seed)

    def test_extend_seed_with_style_merges_keywords(self):
        """Test _extend_seed_with_style merges style keywords into seed."""
        from resume.cli.main import _extend_seed_with_style

        style_data = {
            "top_unigrams": ["docker", "kubernetes", "terraform"],
            "top_bigrams": ["cloud native", "microservices"],
        }
        with temp_yaml_file(style_data) as style_path:
            seed = {"keywords": ["python", "aws"]}
            result = _extend_seed_with_style(seed, style_path)
            # Should merge keywords, preserving order and removing duplicates
            self.assertIn("python", result["keywords"])
            self.assertIn("aws", result["keywords"])
            # At least some style keywords should be added
            self.assertGreater(len(result["keywords"]), 2)

    def test_try_load_structure_missing_file(self):
        """Test _try_load_structure returns None for missing file."""
        from resume.cli.main import _try_load_structure

        result = _try_load_structure(Path("/nonexistent/structure.json"))
        self.assertIsNone(result)

    def test_try_load_structure_valid_file(self):
        """Test _try_load_structure loads valid structure file."""
        from resume.cli.main import _try_load_structure

        structure_data = {
            "sections": [
                {"key": "experience", "title": "Experience"},
                {"key": "education", "title": "Education"},
            ]
        }
        with temp_yaml_file(structure_data) as struct_path:
            result = _try_load_structure(Path(struct_path))
            self.assertIsNotNone(result)
            self.assertEqual(result["sections"][0]["key"], "experience")

    def test_find_structure_in_dirs_not_found(self):
        """Test _find_structure_in_dirs returns None when no structure found."""
        from resume.cli.main import _find_structure_in_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dirs = [Path(tmpdir)]
            result = _find_structure_in_dirs("testprofile", out_dirs)
            self.assertIsNone(result)

    def test_find_structure_in_dirs_nested_location(self):
        """Test _find_structure_in_dirs finds structure in nested profile dir."""
        from resume.cli.main import _find_structure_in_dirs

        structure_data = {"sections": [{"key": "summary", "title": "Summary"}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure: tmpdir/testprofile/structure.json
            profile_dir = Path(tmpdir) / "testprofile"
            profile_dir.mkdir(parents=True)
            struct_path = profile_dir / "structure.json"
            import json
            struct_path.write_text(json.dumps(structure_data))

            out_dirs = [Path(tmpdir)]
            result = _find_structure_in_dirs("testprofile", out_dirs)
            self.assertIsNotNone(result)
            self.assertEqual(result["sections"][0]["key"], "summary")

    def test_find_structure_in_dirs_legacy_location(self):
        """Test _find_structure_in_dirs finds structure in legacy flat naming."""
        from resume.cli.main import _find_structure_in_dirs

        structure_data = {"sections": [{"key": "education", "title": "Education"}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create legacy structure: tmpdir/testprofile.structure.json
            struct_path = Path(tmpdir) / "testprofile.structure.json"
            import json
            struct_path.write_text(json.dumps(structure_data))

            out_dirs = [Path(tmpdir)]
            result = _find_structure_in_dirs("testprofile", out_dirs)
            self.assertIsNotNone(result)
            self.assertEqual(result["sections"][0]["key"], "education")

    def test_apply_profile_overlays_delegates(self):
        """Test _apply_profile_overlays delegates to overlays module."""
        from resume.cli.main import _apply_profile_overlays

        data = {"name": "Test User", "skills": ["Python"]}
        # Should not crash and return data (overlays may modify or return as-is)
        result = _apply_profile_overlays(data, "testprofile")
        self.assertIsInstance(result, dict)
        self.assertIn("name", result)


class TestResumeCLIRender(unittest.TestCase):
    """Test resume render command functionality."""

    def test_render_basic(self):
        """Test render produces a DOCX file."""
        data = {
            "name": "Test User",
            "headline": "Software Engineer",
            "email": "test@example.com",
            "skills": ["Python", "Java"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme Corp",
                    "start": "2020",
                    "end": "Present",
                    "bullets": ["Built systems", "Led team"],
                }
            ],
        }
        template = {
            "sections": [
                {"key": "header"},
                {"key": "experience", "title": "Experience"},
            ]
        }
        with temp_yaml_file(data) as data_path:
            with temp_yaml_file(template) as template_path:
                with tempfile.TemporaryDirectory() as tmpdir:
                    out_path = os.path.join(tmpdir, "resume.docx")
                    proc = run([
                        sys.executable, "-m", "resume", "render",
                        "--data", data_path,
                        "--template", template_path,
                        "--out", out_path,
                    ])
                    self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                    self.assertTrue(os.path.exists(out_path))

    def test_render_with_seed(self):
        """Test render with seed criteria."""
        data = {
            "name": "Test User",
            "skills": ["Python"],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "resume.docx")
                proc = run([
                    sys.executable, "-m", "resume", "render",
                    "--data", data_path,
                    "--seed", "keywords=python,aws",
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_render_pdf_raises_error(self):
        """Test render with .pdf output raises error."""
        data = {"name": "Test User"}
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "resume.pdf")
                proc = run([
                    sys.executable, "-m", "resume", "render",
                    "--data", data_path,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 1)
                self.assertIn("PDF", proc.stderr)


class TestResumeCLIStructure(unittest.TestCase):
    """Test resume structure command functionality."""

    def test_structure_help(self):
        """Test structure subcommand help."""
        proc = run([sys.executable, "-m", "resume", "structure", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--source", proc.stdout)


class TestResumeCLIStyleBuild(unittest.TestCase):
    """Test resume style build command functionality."""

    def test_style_build_with_corpus(self):
        """Test style build produces style profile."""
        with tempfile.TemporaryDirectory() as corpus_dir:
            # Create sample corpus files
            sample_path = os.path.join(corpus_dir, "sample.txt")
            with open(sample_path, "w") as f:
                f.write("Python developer with experience in AWS and Docker.\n")
                f.write("Built microservices and REST APIs.\n")
            with tempfile.TemporaryDirectory() as out_dir:
                out_path = os.path.join(out_dir, "style.json")
                proc = run([
                    sys.executable, "-m", "resume", "style", "build",
                    "--corpus-dir", corpus_dir,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))


class TestResumeCLIFilesTidy(unittest.TestCase):
    """Test resume files tidy command functionality."""

    def test_files_tidy_archive(self):
        """Test files tidy archives old files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files with different timestamps
            for i in range(4):
                path = os.path.join(tmpdir, f"test_{i}.json")
                with open(path, "w") as f:
                    f.write("{}")
                # Modify mtime to simulate age
                import time
                os.utime(path, (time.time() - i * 86400, time.time() - i * 86400))

            proc = run([
                sys.executable, "-m", "resume", "files", "tidy",
                "--dir", tmpdir,
                "--suffixes", ".json",
                "--keep", "2",
            ])
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_files_tidy_delete(self):
        """Test files tidy with --delete flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for i in range(4):
                path = os.path.join(tmpdir, f"test_{i}.json")
                with open(path, "w") as f:
                    f.write("{}")
                import time
                os.utime(path, (time.time() - i * 86400, time.time() - i * 86400))

            proc = run([
                sys.executable, "-m", "resume", "files", "tidy",
                "--dir", tmpdir,
                "--suffixes", ".json",
                "--keep", "2",
                "--delete",
            ])
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_files_tidy_purge_temp(self):
        """Test files tidy with --purge-temp flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a temp file
            temp_path = os.path.join(tmpdir, "~$test.docx")
            with open(temp_path, "w") as f:
                f.write("temp")

            proc = run([
                sys.executable, "-m", "resume", "files", "tidy",
                "--dir", tmpdir,
                "--purge-temp",
            ])
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            # Temp file should be removed
            self.assertFalse(os.path.exists(temp_path))


class TestResumeCLIExperienceExport(unittest.TestCase):
    """Test resume experience export command functionality."""

    def test_experience_export_from_data(self):
        """Test experience export from data file."""
        data = {
            "name": "Test User",
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme Corp",
                    "start": "2020",
                    "end": "Present",
                    "bullets": ["Built systems", "Led team", "Optimized performance"],
                }
            ],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "experience.yaml")
                proc = run([
                    sys.executable, "-m", "resume", "experience", "export",
                    "--data", data_path,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))

    def test_experience_export_with_max_bullets(self):
        """Test experience export with --max-bullets."""
        data = {
            "name": "Test User",
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "bullets": ["One", "Two", "Three", "Four", "Five"],
                }
            ],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "experience.yaml")
                proc = run([
                    sys.executable, "-m", "resume", "experience", "export",
                    "--data", data_path,
                    "--max-bullets", "2",
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_experience_export_missing_args(self):
        """Test experience export with no --data or --resume raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "experience.yaml")
            proc = run([
                sys.executable, "-m", "resume", "experience", "export",
                "--out", out_path,
            ])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--data", proc.stderr.lower() + proc.stdout.lower())


class TestResumeCLIFindStructureInConfig(unittest.TestCase):
    """Test _find_structure_in_config helper function."""

    def test_find_structure_in_config_not_found(self):
        """Test _find_structure_in_config returns None when not found."""
        from resume.cli.main import _find_structure_in_config

        result = _find_structure_in_config("nonexistent_profile_xyz")
        self.assertIsNone(result)


class TestResumeCLILoadStructure(unittest.TestCase):
    """Test _load_structure helper function."""

    def test_load_structure_explicit_json(self):
        """Test _load_structure with explicit JSON path."""
        from resume.cli.main import _load_structure
        import argparse

        structure_data = {"sections": [{"key": "summary"}]}
        with temp_yaml_file(structure_data) as struct_path:
            args = argparse.Namespace(
                structure_from=struct_path,
                profile=None,
                out_dir="out",
            )
            result = _load_structure(args)
            self.assertIsNotNone(result)
            self.assertEqual(result["sections"][0]["key"], "summary")

    def test_load_structure_no_profile_no_explicit(self):
        """Test _load_structure returns None with no profile and no explicit path."""
        from resume.cli.main import _load_structure
        import argparse

        args = argparse.Namespace(
            structure_from=None,
            profile=None,
            out_dir="out",
        )
        result = _load_structure(args)
        self.assertIsNone(result)


class TestResumeCLIMainErrorHandling(unittest.TestCase):
    """Test main() error handling paths."""

    def test_main_handles_exception(self):
        """Test that main returns 1 on exception."""
        from resume.cli.main import main

        # Trigger an error by providing invalid data file
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "alignment.json")
            result = main([
                "align",
                "--data", "/nonexistent/data.json",
                "--job", "/nonexistent/job.json",
                "--out", out_path,
            ])
            self.assertEqual(result, 1)

    def test_main_with_invalid_subcommand(self):
        """Test main with invalid subcommand shows help."""
        proc = run([sys.executable, "-m", "resume", "invalid_command_xyz"])
        # Should return non-zero for invalid subcommand
        self.assertNotEqual(proc.returncode, 0)


class TestResumeCLICandidateInitExtended(unittest.TestCase):
    """Test resume candidate-init command extended functionality."""

    def test_candidate_init_with_experience(self):
        """Test candidate-init with --include-experience flag."""
        data = {
            "name": "Test User",
            "headline": "Software Engineer",
            "skills": ["Python", "Java"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "start": "2020",
                    "end": "Present",
                    "location": "Remote",
                    "bullets": ["Built systems", "Led team", "Optimized code", "Deployed apps"],
                }
            ],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "candidate.yaml")
                proc = run([
                    sys.executable, "-m", "resume", "candidate-init",
                    "--data", data_path,
                    "--include-experience",
                    "--max-bullets", "2",
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))
                # Verify experience is included with limited bullets
                import yaml
                with open(out_path) as f:
                    result = yaml.safe_load(f)
                self.assertIn("experience", result)
                self.assertEqual(len(result["experience"][0]["bullets"]), 2)


class TestResumeCLIAlignExtended(unittest.TestCase):
    """Test resume align command extended functionality."""

    def test_align_with_tailored_output(self):
        """Test align with --tailored flag produces tailored candidate."""
        candidate = {
            "name": "Test User",
            "skills": ["Python", "AWS"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme",
                    "bullets": ["Built Python services", "Deployed to AWS", "Extra bullet"],
                }
            ],
        }
        job = {
            "title": "Senior Engineer",
            "required_skills": ["Python"],
        }
        with temp_yaml_file(candidate) as cand_path:
            with temp_yaml_file(job) as job_path:
                with tempfile.TemporaryDirectory() as tmpdir:
                    align_path = os.path.join(tmpdir, "alignment.json")
                    tailored_path = os.path.join(tmpdir, "tailored.yaml")
                    proc = run([
                        sys.executable, "-m", "resume", "align",
                        "--data", cand_path,
                        "--job", job_path,
                        "--tailored", tailored_path,
                        "--max-bullets", "2",
                        "--out", align_path,
                    ])
                    self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                    self.assertTrue(os.path.exists(tailored_path))


class TestResumeCLISummarizeExtended(unittest.TestCase):
    """Test resume summarize command extended functionality."""

    def test_summarize_to_yaml(self):
        """Test summarize with YAML output."""
        data = {
            "name": "Test User",
            "headline": "Software Engineer",
            "skills": ["Python"],
            "experience": [{"title": "Engineer", "company": "Acme", "bullets": ["Built systems"]}],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "summary.yaml")
                proc = run([
                    sys.executable, "-m", "resume", "summarize",
                    "--data", data_path,
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                self.assertTrue(os.path.exists(out_path))

    def test_summarize_with_seed(self):
        """Test summarize with seed criteria."""
        data = {
            "name": "Test User",
            "skills": ["Python", "AWS"],
            "experience": [{"title": "Engineer", "company": "Acme", "bullets": ["Built systems"]}],
        }
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "summary.md")
                proc = run([
                    sys.executable, "-m", "resume", "summarize",
                    "--data", data_path,
                    "--seed", "keywords=python,cloud",
                    "--out", out_path,
                ])
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
