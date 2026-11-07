"""Tests for the empty-resume guard in cmd_render.

Covers:
- Render of a fully-empty resume raises CLIError with ExitCode.USAGE
- Render with only a name passes (not empty)
- Render with only experience passes
- Render with only skills_groups passes
- Render with only a non-empty summary passes
- Empty scalar summary still triggers the guard
- extract-then-render flow with an unknown profile still renders base data
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import TempDirMixin


class TestHasResumeContent(unittest.TestCase):
    """Unit tests for the _has_resume_content guard helper."""

    def _fn(self, data: dict) -> bool:
        from resume.cli.cmd_render import _has_resume_content
        from resume.schema import Resume
        return _has_resume_content(Resume.from_dict(data))

    def test_empty_resume_has_no_content(self):
        self.assertFalse(self._fn({}))

    def test_name_only_has_content(self):
        self.assertTrue(self._fn({"name": "Jane"}))

    def test_experience_only_has_content(self):
        self.assertTrue(self._fn({"experience": [{"title": "Dev"}]}))

    def test_skills_groups_only_has_content(self):
        self.assertTrue(self._fn({"skills_groups": [{"title": "Languages", "items": ["Python"]}]}))

    def test_non_empty_scalar_summary_has_content(self):
        self.assertTrue(self._fn({"summary": "Real summary here."}))

    def test_empty_scalar_summary_has_no_content(self):
        # "" as a scalar is stored as [PriorityItem(text="")] — truthy list, empty text
        self.assertFalse(self._fn({"summary": ""}))

    def test_list_summary_has_content(self):
        self.assertTrue(self._fn({"summary": [{"text": "A bullet"}]}))

    def test_projects_only_has_content(self):
        """A projects-only resume passes the guard (projects is a registered section)."""
        self.assertTrue(self._fn({"projects": [{"name": "P1"}]}))


class TestCmdRenderEmptyGuard(unittest.TestCase):
    """cmd_render refuses to write when the resume has no content."""

    def _make_args(self, out: str, **overrides):
        import argparse
        args = argparse.Namespace(
            data="data.json",  # non-None so _resolve_data returns immediately
            template=None,
            seed=None,
            style_profile=None,
            filter_skills_alignment=None,
            filter_skills_job=None,
            filter_exp_alignment=None,
            filter_exp_job=None,
            structure_from=None,
            profile=None,
            min_priority=None,
            out=out,
            out_dir=None,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.cmd_render.write_resume_docx")
    @patch("resume.cli.cmd_render._load_structure", return_value=None)
    @patch("resume.cli.cmd_render._apply_filter_pipeline")
    @patch("resume.cli.cmd_render.load_template", return_value={"sections": []})
    @patch("resume.cli.helpers.read_yaml_or_json", return_value={"name": "Test"})
    def test_empty_resume_raises_cli_error(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        """An empty resume raises CLIError before write_resume_docx is called."""
        from resume.cli.cmd_render import cmd_render
        from resume.schema import Resume
        from core.cli_errors import CLIError, ExitCode

        mock_filter.return_value = Resume.from_dict({})
        args = self._make_args(out="out.docx")

        with self.assertRaises(CLIError) as ctx:
            cmd_render(args)

        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        self.assertIn("No content", ctx.exception.message)
        mock_write.assert_not_called()

    @patch("resume.cli.cmd_render.write_resume_docx")
    @patch("resume.cli.cmd_render._load_structure", return_value=None)
    @patch("resume.cli.cmd_render._apply_filter_pipeline")
    @patch("resume.cli.cmd_render.load_template", return_value={"sections": []})
    @patch("resume.cli.helpers.read_yaml_or_json", return_value={"name": "Test"})
    def test_error_message_mentions_data_and_profile(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        """The CLIError message hints at --data and --profile."""
        from resume.cli.cmd_render import cmd_render
        from resume.schema import Resume
        from core.cli_errors import CLIError

        mock_filter.return_value = Resume.from_dict({})
        args = self._make_args(out="out.docx")

        with self.assertRaises(CLIError) as ctx:
            cmd_render(args)

        msg = ctx.exception.message
        self.assertIn("--data", msg)
        self.assertIn("--profile", msg)

    @patch("resume.cli.cmd_render.write_resume_docx")
    @patch("resume.cli.cmd_render._load_structure", return_value=None)
    @patch("resume.cli.cmd_render._apply_filter_pipeline")
    @patch("resume.cli.cmd_render.load_template", return_value={"sections": []})
    @patch("resume.cli.helpers.read_yaml_or_json", return_value={"name": "Test"})
    def test_resume_with_name_passes_guard(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        """A resume with a name is not blocked by the guard."""
        from resume.cli.cmd_render import cmd_render
        from resume.schema import Resume

        mock_filter.return_value = Resume.from_dict({"name": "Jane Doe"})
        args = self._make_args(out="out.docx")
        result = cmd_render(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

    @patch("resume.cli.cmd_render.write_resume_docx")
    @patch("resume.cli.cmd_render._load_structure", return_value=None)
    @patch("resume.cli.cmd_render._apply_filter_pipeline")
    @patch("resume.cli.cmd_render.load_template", return_value={"sections": []})
    @patch("resume.cli.helpers.read_yaml_or_json", return_value={"name": "Test"})
    def test_projects_only_resume_passes_guard(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        """A resume with only projects is not blocked by the guard."""
        from resume.cli.cmd_render import cmd_render
        from resume.schema import Resume

        mock_filter.return_value = Resume.from_dict({"projects": [{"name": "P1"}]})
        args = self._make_args(out="out.docx")
        result = cmd_render(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()


class TestExtractThenRenderUnknownProfile(TempDirMixin, unittest.TestCase):
    """extract → render flow with an unknown profile still renders extracted data."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_render_with_unknown_profile_renders_base_data(self):
        """render --profile X with no overlay dir still renders the --data content."""
        import io
        from resume.cli.main import main
        from tests.resume_tests.fixtures import make_candidate

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        data_dir = Path(self.tmpdir) / "data"
        data_dir.mkdir()
        data_file = data_dir / "data.json"
        import json
        data_file.write_text(json.dumps(make_candidate()))

        out_file = Path(self.tmpdir) / "resume.docx"
        buf = io.StringIO()

        with self.in_tmpdir():
            with patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                with patch("sys.stderr", buf):
                    exit_code = main([
                        "render",
                        "--data", str(data_file),
                        "--profile", "nonexistent_profile_xyz",
                        "--out", str(out_file),
                    ])

        # The warning must name the profile
        self.assertIn("nonexistent_profile_xyz", buf.getvalue())
        # Must exit 0 (render succeeded with base data, overlay skipped)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
