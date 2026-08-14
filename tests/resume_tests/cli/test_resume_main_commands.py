"""Resume command function tests: structure helpers and command execution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestStructureHelpersRealFiles(unittest.TestCase):
    """Real-filesystem coverage for structure helpers.

    The mock-based tests below patch _try_load_structure itself, which
    bypasses the real multi-extension resolution order and the real
    nested-vs-legacy Path.exists() precedence. These exercise that logic
    against an actual filesystem.
    """

    def test_try_load_structure_loads_existing_yaml(self):
        from resume.cli.main import _try_load_structure

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("sections:\n  - experience\n  - education\n")
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertEqual(result, {"sections": ["experience", "education"]})
        finally:
            path.unlink()

    def test_try_load_structure_loads_existing_json(self):
        from resume.cli.main import _try_load_structure

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write('{"sections": ["skills"]}')
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertEqual(result, {"sections": ["skills"]})
        finally:
            path.unlink()

    def test_try_load_structure_returns_none_for_invalid_yaml(self):
        from resume.cli.main import _try_load_structure

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("invalid: yaml: content: [")
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertIsNone(result)
        finally:
            path.unlink()

    def test_find_structure_in_dirs_prefers_nested_over_legacy_on_disk(self):
        """With both a nested and a legacy file for real, nested must win."""
        from resume.cli.main import _find_structure_in_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prof_dir = tmp / "myprofile"
            prof_dir.mkdir()
            (prof_dir / "structure.yaml").write_text("source: nested\n")
            (tmp / "myprofile.structure.yaml").write_text("source: legacy\n")

            result = _find_structure_in_dirs("myprofile", [tmp])
            self.assertEqual(result, {"source": "nested"})

    def test_find_structure_in_dirs_searches_multiple_dirs_in_order(self):
        from resume.cli.main import _find_structure_in_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            second_dir = tmp / "second"
            second_dir.mkdir()
            (second_dir / "myprofile.structure.json").write_text('{"found": true}')

            result = _find_structure_in_dirs("myprofile", [tmp, second_dir])
            self.assertEqual(result, {"found": True})

    def test_find_structure_in_dirs_tries_multiple_extensions(self):
        """.yml (not just .yaml/.json) must be resolved for a real file."""
        from resume.cli.main import _find_structure_in_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prof_dir = tmp / "myprofile"
            prof_dir.mkdir()
            (prof_dir / "structure.yml").write_text("ext: yml\n")

            result = _find_structure_in_dirs("myprofile", [tmp])
            self.assertEqual(result, {"ext": "yml"})


class TestStructureHelpers(unittest.TestCase):
    """Test structure loading helper functions."""

    def test_try_load_structure_nonexistent_file(self):
        """Test _try_load_structure returns None for nonexistent file."""
        from resume.cli.main import _try_load_structure
        from pathlib import Path

        result = _try_load_structure(Path("nonexistent/file.json"))
        self.assertIsNone(result)

    @patch('resume.cli.main.read_yaml_or_json')
    def test_try_load_structure_success(self, mock_read):
        """Test _try_load_structure loads valid structure."""
        from resume.cli.main import _try_load_structure
        from pathlib import Path

        mock_read.return_value = {"sections": ["header", "experience"]}

        with patch.object(Path, 'exists', return_value=True):
            result = _try_load_structure(Path("valid.json"))
            self.assertEqual(result, {"sections": ["header", "experience"]})

    @patch('resume.cli.main.read_yaml_or_json')
    def test_try_load_structure_exception(self, mock_read):
        """Test _try_load_structure returns None on read error."""
        from resume.cli.main import _try_load_structure
        from pathlib import Path

        mock_read.side_effect = RuntimeError("Parse error")

        with patch.object(Path, 'exists', return_value=True):
            result = _try_load_structure(Path("invalid.json"))
            self.assertIsNone(result)

    @patch('resume.cli.main._try_load_structure')
    def test_find_structure_in_dirs_nested(self, mock_try_load):
        """Test _find_structure_in_dirs finds nested structure."""
        from resume.cli.main import _find_structure_in_dirs
        from pathlib import Path

        mock_try_load.side_effect = lambda p: {"sections": []} if "out/prof/structure" in str(p) else None

        result = _find_structure_in_dirs("prof", [Path("out")])
        self.assertEqual(result, {"sections": []})

    @patch('resume.cli.main._try_load_structure')
    def test_find_structure_in_dirs_legacy(self, mock_try_load):
        """Test _find_structure_in_dirs finds legacy flat structure."""
        from resume.cli.main import _find_structure_in_dirs
        from pathlib import Path

        # Return None for nested, structure for legacy
        def side_effect(p):
            if "prof/structure" in str(p):
                return None
            if "prof.structure" in str(p):
                return {"sections": ["legacy"]}
            return None

        mock_try_load.side_effect = side_effect

        result = _find_structure_in_dirs("prof", [Path("out")])
        self.assertEqual(result, {"sections": ["legacy"]})

    @patch('resume.cli.main._try_load_structure')
    def test_find_structure_in_config(self, mock_try_load):
        """Test _find_structure_in_config searches config directory."""
        from resume.cli.main import _find_structure_in_config

        mock_try_load.side_effect = lambda p: {"sections": []} if "config/profiles" in str(p) else None

        result = _find_structure_in_config("prof")
        self.assertEqual(result, {"sections": []})

    @patch('resume.cli.main.infer_structure_from_docx')
    def test_load_structure_from_docx(self, mock_infer):
        """Test _load_structure loads from DOCX."""
        from resume.cli.main import _load_structure

        mock_infer.return_value = {"sections": ["from_docx"]}

        args = MagicMock()
        args.structure_from = "template.docx"

        result = _load_structure(args)
        self.assertEqual(result, {"sections": ["from_docx"]})
        mock_infer.assert_called_once_with("template.docx")

    @patch('resume.cli.main._try_load_structure')
    def test_load_structure_from_json_path(self, mock_try_load):
        """Test _load_structure loads from JSON path."""
        from resume.cli.main import _load_structure

        mock_try_load.return_value = {"sections": ["from_json"]}

        args = MagicMock()
        args.structure_from = "structure.json"

        result = _load_structure(args)
        self.assertEqual(result, {"sections": ["from_json"]})

    @patch('resume.cli.main._find_structure_in_dirs')
    def test_load_structure_auto_discover(self, mock_find_dirs):
        """Test _load_structure auto-discovers from profile."""
        from resume.cli.main import _load_structure

        mock_find_dirs.return_value = {"sections": ["auto"]}

        args = MagicMock()
        args.structure_from = None
        args.profile = "test_profile"
        args.out_dir = "out"

        result = _load_structure(args)
        self.assertEqual(result, {"sections": ["auto"]})

    def test_load_structure_no_profile(self):
        """Test _load_structure returns None when no profile."""
        from resume.cli.main import _load_structure

        args = MagicMock()
        args.structure_from = None
        args.profile = None

        result = _load_structure(args)
        self.assertIsNone(result)


class TestResumeCommands(unittest.TestCase):
    """Test resume command functions."""

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.merge_profiles')
    @patch('resume.cli.main.read_text_any')
    def test_cmd_extract_text_files(self, mock_read_text, mock_merge, mock_write):
        """Test cmd_extract with text files."""
        from resume.cli.main import cmd_extract

        mock_read_text.return_value = "Resume text"
        mock_merge.return_value = {"name": "John Doe"}

        args = MagicMock()
        args.linkedin = "profile.txt"
        args.resume = "resume.txt"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_extract(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.merge_profiles')
    @patch('resume.cli.main.read_text_raw')
    @patch('resume.cli.main.read_text_any')
    def test_cmd_extract_html_linkedin(self, mock_read_any, mock_read_raw, mock_merge, mock_write):
        """Test cmd_extract with HTML LinkedIn file."""
        from resume.cli.main import cmd_extract

        mock_read_raw.return_value = "<html>LinkedIn profile</html>"
        mock_read_any.return_value = "Resume text"
        mock_merge.return_value = {"name": "John Doe"}

        args = MagicMock()
        args.linkedin = "profile.html"
        args.resume = "resume.txt"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_extract(args)
        self.assertEqual(result, 0)
        mock_read_raw.assert_called_once_with("profile.html")

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.merge_profiles')
    @patch('resume.parsing_experience_docx.parse_resume_docx')
    @patch('resume.cli.main.read_text_any')
    def test_cmd_extract_docx_resume(self, mock_read_any, mock_parse_docx, mock_merge, mock_write):
        """Test cmd_extract with DOCX resume."""
        from resume.cli.main import cmd_extract

        mock_read_any.return_value = "LinkedIn text"
        mock_parse_docx.return_value = {"skills": ["Python"]}
        mock_merge.return_value = {"name": "John Doe"}

        args = MagicMock()
        args.linkedin = "profile.txt"
        args.resume = "resume.docx"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_extract(args)
        self.assertEqual(result, 0)
        mock_parse_docx.assert_called_once_with("resume.docx")

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.merge_profiles')
    @patch('resume.parsing_experience_pdf.parse_resume_pdf')
    @patch('resume.cli.main.read_text_any')
    def test_cmd_extract_pdf_resume(self, mock_read_any, mock_parse_pdf, mock_merge, mock_write):
        """Test cmd_extract with PDF resume."""
        from resume.cli.main import cmd_extract

        mock_read_any.return_value = "LinkedIn text"
        mock_parse_pdf.return_value = {"skills": ["Java"]}
        mock_merge.return_value = {"name": "Jane Doe"}

        args = MagicMock()
        args.linkedin = "profile.txt"
        args.resume = "resume.pdf"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_extract(args)
        self.assertEqual(result, 0)
        mock_parse_pdf.assert_called_once_with("resume.pdf")

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.merge_profiles')
    @patch('resume.cli.main.parse_linkedin_text')
    def test_cmd_extract_linkedin_only(self, mock_parse_li, mock_merge, mock_write):
        """Test cmd_extract with LinkedIn only."""
        from resume.cli.main import cmd_extract

        mock_parse_li.return_value = {"name": "Test User"}
        mock_merge.return_value = {"name": "Test User"}

        args = MagicMock()
        args.linkedin = None
        args.resume = None
        args.out = "output.json"
        args.profile = None
        args.out_dir = "out"

        result = cmd_extract(args)
        self.assertEqual(result, 0)

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.infer_structure_from_docx')
    def test_cmd_structure(self, mock_infer, mock_write):
        """Test cmd_structure command."""
        from resume.cli.main import cmd_structure

        mock_infer.return_value = {"sections": ["header", "experience"]}

        args = MagicMock()
        args.source = "reference.docx"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_structure(args)
        self.assertEqual(result, 0)
        mock_infer.assert_called_once_with("reference.docx")
        mock_write.assert_called_once()

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.build_keyword_spec')
    @patch('resume.cli.main.load_job_config')
    @patch('resume.cli.main.align_candidate_to_job')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_align_without_tailored(self, mock_read, mock_align, mock_load_job, mock_build_kw, mock_write):
        """Test cmd_align without tailored output."""
        from resume.cli.main import cmd_align

        mock_read.return_value = {"name": "Test"}
        mock_load_job.return_value = {"title": "Engineer"}
        mock_build_kw.return_value = ({"python": 1}, {})
        mock_align.return_value = {"score": 85}

        args = MagicMock()
        args.data = "candidate.json"
        args.job = "job.yaml"
        args.tailored = None
        args.out = None
        args.profile = "test"
        args.out_dir = "out"
        args.max_bullets = 6
        args.min_exp_score = 1

        result = cmd_align(args)
        self.assertEqual(result, 0)
        mock_align.assert_called_once()

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.build_tailored_candidate')
    @patch('resume.cli.main.build_keyword_spec')
    @patch('resume.cli.main.load_job_config')
    @patch('resume.cli.main.align_candidate_to_job')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_align_with_tailored(self, mock_read, mock_align, mock_load_job, mock_build_kw, mock_build_tailored, mock_write):
        """Test cmd_align with tailored output."""
        from resume.cli.main import cmd_align

        mock_read.return_value = {"name": "Test"}
        mock_load_job.return_value = {"title": "Engineer"}
        mock_build_kw.return_value = ({"python": 1}, {})
        mock_align.return_value = {"score": 85}
        mock_build_tailored.return_value = {"name": "Test", "filtered": True}

        args = MagicMock()
        args.data = "candidate.json"
        args.job = "job.yaml"
        args.tailored = "tailored.json"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"
        args.max_bullets = 6
        args.min_exp_score = 1

        result = cmd_align(args)
        self.assertEqual(result, 0)
        mock_build_tailored.assert_called_once()
        # Should write both alignment and tailored
        self.assertEqual(mock_write.call_count, 2)

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_candidate_init_without_experience(self, mock_read, mock_write):
        """Test cmd_candidate_init without experience."""
        from resume.cli.main import cmd_candidate_init

        mock_read.return_value = {
            "name": "John Doe",
            "headline": "Software Engineer",
            "email": "john@example.com",
            "phone": "555-1234",
            "location": "San Francisco",
            "skills": ["Python", "Docker"],
        }

        args = MagicMock()
        args.data = "data.json"
        args.include_experience = False
        args.max_bullets = 3
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_candidate_init(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

        # Check that experience was not included
        written_data = mock_write.call_args[0][0]
        self.assertNotIn("experience", written_data)

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_candidate_init_with_experience(self, mock_read, mock_write):
        """Test cmd_candidate_init with experience."""
        from resume.cli.main import cmd_candidate_init

        mock_read.return_value = {
            "name": "John Doe",
            "headline": "Software Engineer",
            "email": "john@example.com",
            "skills": ["Python"],
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Tech Co",
                    "start": "2020",
                    "end": "2023",
                    "location": "SF",
                    "bullets": ["Did thing 1", "Did thing 2", "Did thing 3", "Did thing 4"],
                }
            ],
        }

        args = MagicMock()
        args.data = "data.json"
        args.include_experience = True
        args.max_bullets = 2
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_candidate_init(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

        # Check that experience was included and bullets limited
        written_data = mock_write.call_args[0][0]
        self.assertIn("experience", written_data)
        self.assertEqual(len(written_data["experience"][0]["bullets"]), 2)

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.style.build_style_profile')
    def test_cmd_style_build(self, mock_build, mock_write):
        """Test cmd_style_build command."""
        from resume.cli.main import cmd_style_build

        mock_build.return_value = {"word_freq": {"leadership": 10}}

        args = MagicMock()
        args.corpus_dir = "corpus"
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_style_build(args)
        self.assertEqual(result, 0)
        mock_build.assert_called_once_with("corpus")
        mock_write.assert_called_once()

    @patch('resume.cli.main.write_text')
    @patch('resume.cli.main.build_summary')
    @patch('resume.cli.main.FilterPipeline')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_summarize_markdown_output(self, mock_read, mock_pipeline_class, mock_build_summary, mock_write_text):
        """Test cmd_summarize with markdown output."""
        from resume.cli.main import cmd_summarize

        mock_read.return_value = {"name": "Test"}
        mock_pipeline = MagicMock()
        mock_pipeline.with_profile_overlays.return_value = mock_pipeline
        mock_pipeline.with_skill_filter.return_value = mock_pipeline
        mock_pipeline.with_experience_filter.return_value = mock_pipeline
        mock_pipeline.execute.return_value = {"name": "Test"}
        mock_pipeline_class.return_value = mock_pipeline

        mock_build_summary.return_value = {
            "headline": "Software Engineer",
            "top_skills": ["Python", "Docker"],
            "experience_highlights": ["Built systems", "Led teams"],
        }

        args = MagicMock()
        args.data = "data.json"
        args.seed = None
        args.style_profile = None
        args.filter_skills_alignment = None
        args.filter_skills_job = None
        args.filter_exp_alignment = None
        args.filter_exp_job = None
        args.out = None
        args.profile = "test"
        args.out_dir = "out"

        result = cmd_summarize(args)
        self.assertEqual(result, 0)
        mock_write_text.assert_called_once()

        # Check markdown formatting
        written_text = mock_write_text.call_args[0][1]
        self.assertIn("# Resume Summary", written_text)
        self.assertIn("## Headline", written_text)
        self.assertIn("Software Engineer", written_text)
        self.assertIn("## Top Skills", written_text)
        self.assertIn("Python, Docker", written_text)

    @patch('resume.cli.main.write_yaml_or_json')
    @patch('resume.cli.main.build_summary')
    @patch('resume.cli.main.FilterPipeline')
    @patch('resume.cli.main.read_yaml_or_json')
    def test_cmd_summarize_json_output(self, mock_read, mock_pipeline_class, mock_build_summary, mock_write_json):
        """Test cmd_summarize with JSON output."""
        from resume.cli.main import cmd_summarize

        mock_read.return_value = {"name": "Test"}
        mock_pipeline = MagicMock()
        mock_pipeline.with_profile_overlays.return_value = mock_pipeline
        mock_pipeline.with_skill_filter.return_value = mock_pipeline
        mock_pipeline.with_experience_filter.return_value = mock_pipeline
        mock_pipeline.execute.return_value = {"name": "Test"}
        mock_pipeline_class.return_value = mock_pipeline

        mock_build_summary.return_value = {"headline": "Engineer"}

        args = MagicMock()
        args.data = "data.json"
        args.seed = None
        args.style_profile = None
        args.filter_skills_alignment = None
        args.filter_skills_job = None
        args.filter_exp_alignment = None
        args.filter_exp_job = None
        args.out = "summary.json"
        args.profile = None
        args.out_dir = "out"

        result = cmd_summarize(args)
        self.assertEqual(result, 0)
        mock_write_json.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
