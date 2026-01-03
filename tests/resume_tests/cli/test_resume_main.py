"""Tests for resume/__main__.py module."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import repo_root, run


class TestResumeMain(unittest.TestCase):
    """Test resume/__main__.py module entry point."""

    def test_main_import_exists(self):
        """Test that main function can be imported from __main__."""
        from resume.__main__ import main

        self.assertIsNotNone(main)
        self.assertTrue(callable(main))

    def test_module_invocation_help(self):
        """Test that python -m resume --help works."""
        root = repo_root()
        proc = run([sys.executable, "-m", "resume", "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("resume", proc.stdout.lower())

    def test_main_returns_zero_with_help(self):
        """Test that main returns 0 when showing help."""
        from resume.__main__ import main

        # Help exits with 0
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_agentic_flag(self):
        """Test --agentic flag works via module."""
        proc = run([sys.executable, "-m", "resume", "--agentic"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("agentic: resume", proc.stdout)


class TestResumeCliMain(unittest.TestCase):
    """Test resume/cli/main.py main() function."""

    def test_main_returns_zero_for_agentic(self):
        """Test main() returns 0 for agentic output."""
        from resume.cli.main import main

        result = main(["--agentic"])
        self.assertEqual(result, 0)

    def test_main_no_command_shows_help(self):
        """Test main() shows help when no command provided."""
        from resume.cli.main import main

        result = main([])
        self.assertEqual(result, 0)

    def test_emit_agentic_function(self):
        """Test _emit_agentic() loads agentic emit function."""
        from resume.cli.main import _emit_agentic

        result = _emit_agentic("yaml", compact=True)
        self.assertEqual(result, 0)


class TestResumeCommandHelpers(unittest.TestCase):
    """Test resume command helper functions."""

    def test_resolve_out_with_explicit_out(self):
        """Test _resolve_out uses explicit --out path."""
        from resume.cli.main import _resolve_out
        from pathlib import Path

        args = MagicMock()
        args.out = "custom/path.json"
        args.profile = None
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path("custom/path.json"))

    def test_resolve_out_with_profile(self):
        """Test _resolve_out generates path from profile."""
        from resume.cli.main import _resolve_out
        from pathlib import Path

        args = MagicMock()
        args.out = None
        args.profile = "test_profile"
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path("out/test_profile/data.json"))

    def test_resolve_out_default(self):
        """Test _resolve_out uses DEFAULT_PROFILE when no profile."""
        from resume.cli.main import _resolve_out, DEFAULT_PROFILE
        from pathlib import Path

        args = MagicMock()
        args.out = None
        args.profile = None
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path(f"out/{DEFAULT_PROFILE}/data.json"))

    def test_extend_seed_with_style_no_profile(self):
        """Test _extend_seed_with_style returns seed unchanged when no style profile."""
        from resume.cli.main import _extend_seed_with_style

        seed = {"keywords": ["python", "testing"]}
        result = _extend_seed_with_style(seed, None)
        self.assertEqual(result, seed)

    @patch('resume.cli.main.read_yaml_or_json')
    @patch('resume.style.extract_style_keywords')
    def test_extend_seed_with_style_adds_keywords(self, mock_extract, mock_read):
        """Test _extend_seed_with_style adds style keywords to seed."""
        from resume.cli.main import _extend_seed_with_style

        mock_read.return_value = {"style": "data"}
        mock_extract.return_value = ["leadership", "management"]

        seed = {"keywords": ["python"]}
        result = _extend_seed_with_style(seed, "style.json")

        # Should have original + new keywords
        self.assertIn("python", result["keywords"])
        self.assertIn("leadership", result["keywords"])
        self.assertIn("management", result["keywords"])

    def test_extend_seed_with_style_handles_string_keywords(self):
        """Test _extend_seed_with_style converts string keywords to list."""
        from resume.cli.main import _extend_seed_with_style
        from unittest.mock import patch

        with patch('resume.cli.main.read_yaml_or_json') as mock_read:
            with patch('resume.style.extract_style_keywords') as mock_extract:
                mock_read.return_value = {"style": "data"}
                mock_extract.return_value = ["new_kw"]

                seed = {"keywords": "single_keyword"}
                result = _extend_seed_with_style(seed, "style.json")

                self.assertIn("single_keyword", result["keywords"])
                self.assertIn("new_kw", result["keywords"])

    def test_extend_seed_with_style_exception_handling(self):
        """Test _extend_seed_with_style handles exceptions gracefully."""
        from resume.cli.main import _extend_seed_with_style
        from unittest.mock import patch

        with patch('resume.cli.main.read_yaml_or_json') as mock_read:
            mock_read.side_effect = RuntimeError("File not found")

            seed = {"keywords": ["python"]}
            result = _extend_seed_with_style(seed, "style.json")

            # Should return original seed unchanged
            self.assertEqual(result, seed)


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
    @patch('resume.parsing.parse_resume_docx')
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
    @patch('resume.parsing.parse_resume_pdf')
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
