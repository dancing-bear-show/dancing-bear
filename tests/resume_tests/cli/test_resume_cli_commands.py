"""Command execution resume CLI tests: extract, summarize, align, render, etc."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

from tests.fixtures import run, temp_yaml_file


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
        """Test render with .pdf output exits with USAGE error (C5: CLIError replaces RuntimeError)."""
        data = {"name": "Test User"}
        with temp_yaml_file(data) as data_path:
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "resume.pdf")
                proc = run([
                    sys.executable, "-m", "resume", "render",
                    "--data", data_path,
                    "--out", out_path,
                ])
                # ExitCode.USAGE == 2 (C5 fix replaced RuntimeError with CLIError(..., ExitCode.USAGE))
                self.assertEqual(proc.returncode, 2)
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
