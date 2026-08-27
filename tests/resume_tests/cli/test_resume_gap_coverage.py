"""Gap coverage tests for resume.cli.main — command functions not fully covered.

Covers the remaining uncovered lines in:
  - cmd_render (lines 357-386): happy path via mocked write_resume_docx + sad paths
  - cmd_align profile overlay branch (line 415-417)
  - cmd_candidate_init profile overlay branch (line 442-444)
  - cmd_files_tidy unit-level (lines 509-526): archive, delete, purge-temp branches
  - cmd_experience_export (lines 541-560): data, resume-file paths, missing-arg exit
  - cmd_export_pdf (lines 651-677): happy path + sad paths (missing file, conversion fail)

Every error path is paired with a corresponding happy-path test per concerns/tests.md.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# cmd_render
# ---------------------------------------------------------------------------


class TestCmdRenderUnit(unittest.TestCase):
    """Unit tests for cmd_render — mocked dependencies, targeting lines 357-386."""

    def _make_args(self, **overrides) -> MagicMock:
        args = MagicMock()
        args.data = "data.json"
        args.template = None
        args.seed = None
        args.style_profile = None
        args.filter_skills_alignment = None
        args.filter_skills_job = None
        args.filter_exp_alignment = None
        args.filter_exp_job = None
        args.structure_from = None
        args.profile = "sample"
        args.min_priority = None
        args.out = None
        args.out_dir = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.main.write_resume_docx")
    @patch("resume.cli.main._load_structure", return_value=None)
    @patch("resume.cli.main._apply_filter_pipeline")
    @patch("resume.cli.main.load_template", return_value={"sections": []})
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_happy_path_returns_zero(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        from resume.cli.main import cmd_render

        mock_filter.return_value = {"name": "Test"}
        args = self._make_args(out="out.docx")
        result = cmd_render(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

    @patch("resume.cli.main.write_resume_docx")
    @patch("resume.cli.main._load_structure", return_value=None)
    @patch("resume.cli.main._apply_filter_pipeline")
    @patch("resume.cli.main.load_template", return_value={"sections": []})
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_calls_write_resume_docx_with_correct_args(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        from resume.cli.main import cmd_render

        mock_filter.return_value = {"name": "Test", "skills": ["Python"]}
        args = self._make_args(out="out.docx")
        cmd_render(args)
        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args.kwargs
        self.assertIn("data", call_kwargs)
        self.assertIn("template", call_kwargs)
        self.assertIn("out_path", call_kwargs)
        self.assertIn("seed", call_kwargs)
        self.assertIn("structure", call_kwargs)

    @patch("resume.cli.main._apply_filter_pipeline")
    @patch("resume.cli.main._load_structure", return_value=None)
    @patch("resume.cli.main.load_template", return_value={})
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_pdf_output_raises_cli_error_exit_code_2(
        self, mock_read, mock_template, mock_structure, mock_filter
    ) -> None:
        """render must refuse .pdf output with ExitCode.USAGE (2)."""
        from core.cli_errors import CLIError, ExitCode

        mock_filter.return_value = {"name": "Test"}
        args = self._make_args(out="out.pdf")
        with self.assertRaises(CLIError) as ctx:
            from resume.cli.main import cmd_render
            cmd_render(args)
        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        self.assertIn("export-pdf", str(ctx.exception))

    @patch("resume.cli.main.write_resume_docx")
    @patch("resume.cli.main._load_structure", return_value=None)
    @patch("resume.cli.main._apply_filter_pipeline")
    @patch("resume.cli.main.load_template", return_value={})
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_min_priority_float_passed_to_filter(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        from resume.cli.main import cmd_render

        mock_filter.return_value = {"name": "Test"}
        args = self._make_args(out="out.docx", min_priority=0.7)
        cmd_render(args)
        # _apply_filter_pipeline is called with the float value
        call_args = mock_filter.call_args
        self.assertEqual(call_args[0][2], 0.7)  # third positional arg is min_priority

    @patch("resume.cli.main.write_resume_docx")
    @patch("resume.cli.main._load_structure", return_value=None)
    @patch("resume.cli.main._apply_filter_pipeline")
    @patch("resume.cli.main.load_template", return_value={})
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_none_min_priority_passed_as_none(
        self, mock_read, mock_template, mock_filter, mock_structure, mock_write
    ) -> None:
        from resume.cli.main import cmd_render

        mock_filter.return_value = {"name": "Test"}
        args = self._make_args(out="out.docx", min_priority=None)
        cmd_render(args)
        call_args = mock_filter.call_args
        self.assertIsNone(call_args[0][2])


# ---------------------------------------------------------------------------
# cmd_align profile overlay branch
# ---------------------------------------------------------------------------


class TestCmdAlignProfileOverlay(unittest.TestCase):
    """Tests for cmd_align lines 415-417 (profile overlay branch)."""

    def _make_args(self, **overrides) -> MagicMock:
        args = MagicMock()
        args.data = "candidate.json"
        args.job = "job.yaml"
        args.tailored = None
        args.out = "alignment.json"
        args.out_dir = None
        args.max_bullets = 6
        args.min_exp_score = 1
        args.profile = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.align_candidate_to_job", return_value={"score": 80})
    @patch("resume.cli.main.build_keyword_spec", return_value=({"python": 1}, {}))
    @patch("resume.cli.main.load_job_config", return_value={"title": "Eng"})
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_profile_overlay_applied_when_profile_set(
        self, mock_read, mock_overlay, mock_load_job, mock_build_kw, mock_align, mock_write
    ) -> None:
        from resume.cli.main import cmd_align

        mock_overlay.return_value = {"name": "Test", "overlaid": True}
        args = self._make_args(profile="myprofile")
        result = cmd_align(args)
        self.assertEqual(result, 0)
        mock_overlay.assert_called_once_with({"name": "Test"}, "myprofile")
        # align received the overlaid data
        align_call_data = mock_align.call_args[0][0]
        self.assertTrue(align_call_data.get("overlaid"))

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.align_candidate_to_job", return_value={"score": 80})
    @patch("resume.cli.main.build_keyword_spec", return_value=({"python": 1}, {}))
    @patch("resume.cli.main.load_job_config", return_value={"title": "Eng"})
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_profile_overlay_skipped_when_no_profile(
        self, mock_read, mock_overlay, mock_load_job, mock_build_kw, mock_align, mock_write
    ) -> None:
        from resume.cli.main import cmd_align

        args = self._make_args(profile=None)
        cmd_align(args)
        mock_overlay.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_candidate_init profile overlay branch
# ---------------------------------------------------------------------------


class TestCmdCandidateInitProfileOverlay(unittest.TestCase):
    """Tests for cmd_candidate_init lines 442-444 (profile overlay branch)."""

    def _make_args(self, **overrides) -> MagicMock:
        args = MagicMock()
        args.data = "data.json"
        args.include_experience = False
        args.max_bullets = 3
        args.out = "candidate.yaml"
        args.out_dir = None
        args.profile = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test", "skills": ["Python"]})
    def test_profile_overlay_applied_when_profile_given(
        self, mock_read, mock_overlay, mock_write
    ) -> None:
        from resume.cli.main import cmd_candidate_init

        mock_overlay.return_value = {"name": "Test", "skills": ["Python", "Go"]}
        args = self._make_args(profile="myprofile")
        result = cmd_candidate_init(args)
        self.assertEqual(result, 0)
        mock_overlay.assert_called_once_with({"name": "Test", "skills": ["Python"]}, "myprofile")

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test", "skills": ["Python"]})
    def test_no_overlay_when_profile_none(
        self, mock_read, mock_overlay, mock_write
    ) -> None:
        from resume.cli.main import cmd_candidate_init

        args = self._make_args(profile=None)
        cmd_candidate_init(args)
        mock_overlay.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_files_tidy (unit-level paths through lines 509-526)
# ---------------------------------------------------------------------------


class TestCmdFilesTidyUnit(unittest.TestCase):
    """Unit-level tests for cmd_files_tidy — exercise archive, delete, purge branches."""

    def _make_args(self, **overrides) -> MagicMock:
        args = MagicMock()
        args.dir = "_data"
        args.prefix = None
        args.suffixes = ".json,.docx"
        args.keep = 2
        args.archive_dir = None
        args.delete = False
        args.purge_temp = False
        args.subfolder = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.main.purge_temp_files")
    @patch("resume.cli.main.execute_archive")
    @patch("resume.cli.main.execute_delete")
    @patch("resume.cli.main.build_tidy_plan")
    def test_happy_path_archive_returns_zero(
        self, mock_plan, mock_delete, mock_archive, mock_purge
    ) -> None:
        from resume.cli.main import cmd_files_tidy

        plan = MagicMock()
        plan.move = [Path("old.json")]
        mock_plan.return_value = plan
        args = self._make_args(delete=False, purge_temp=False)
        result = cmd_files_tidy(args)
        self.assertEqual(result, 0)
        mock_archive.assert_called_once()
        mock_delete.assert_not_called()
        mock_purge.assert_not_called()

    @patch("resume.cli.main.purge_temp_files")
    @patch("resume.cli.main.execute_archive")
    @patch("resume.cli.main.execute_delete")
    @patch("resume.cli.main.build_tidy_plan")
    def test_delete_flag_calls_execute_delete_not_archive(
        self, mock_plan, mock_delete, mock_archive, mock_purge
    ) -> None:
        from resume.cli.main import cmd_files_tidy

        plan = MagicMock()
        plan.move = [Path("old.json")]
        mock_plan.return_value = plan
        args = self._make_args(delete=True, purge_temp=False)
        result = cmd_files_tidy(args)
        self.assertEqual(result, 0)
        mock_delete.assert_called_once()
        mock_archive.assert_not_called()

    @patch("resume.cli.main.purge_temp_files")
    @patch("resume.cli.main.execute_archive")
    @patch("resume.cli.main.execute_delete")
    @patch("resume.cli.main.build_tidy_plan")
    def test_purge_temp_flag_calls_purge_temp_files(
        self, mock_plan, mock_delete, mock_archive, mock_purge
    ) -> None:
        from resume.cli.main import cmd_files_tidy

        plan = MagicMock()
        plan.move = []  # Nothing to archive/delete
        mock_plan.return_value = plan
        args = self._make_args(purge_temp=True)
        result = cmd_files_tidy(args)
        self.assertEqual(result, 0)
        mock_purge.assert_called_once_with(args.dir)
        mock_archive.assert_not_called()
        mock_delete.assert_not_called()

    @patch("resume.cli.main.purge_temp_files")
    @patch("resume.cli.main.execute_archive")
    @patch("resume.cli.main.execute_delete")
    @patch("resume.cli.main.build_tidy_plan")
    def test_empty_move_list_skips_archive_and_delete(
        self, mock_plan, mock_delete, mock_archive, mock_purge
    ) -> None:
        from resume.cli.main import cmd_files_tidy

        plan = MagicMock()
        plan.move = []
        mock_plan.return_value = plan
        args = self._make_args(delete=False, purge_temp=False)
        result = cmd_files_tidy(args)
        self.assertEqual(result, 0)
        mock_archive.assert_not_called()
        mock_delete.assert_not_called()

    @patch("resume.cli.main.purge_temp_files")
    @patch("resume.cli.main.execute_archive")
    @patch("resume.cli.main.execute_delete")
    @patch("resume.cli.main.build_tidy_plan")
    def test_suffixes_parsed_and_passed_to_plan(
        self, mock_plan, mock_delete, mock_archive, mock_purge
    ) -> None:
        from resume.cli.main import cmd_files_tidy

        plan = MagicMock()
        plan.move = []
        mock_plan.return_value = plan
        args = self._make_args(suffixes=".json, .yaml ,  .docx ")
        cmd_files_tidy(args)
        call_kwargs = mock_plan.call_args.kwargs
        self.assertEqual(call_kwargs["suffixes"], [".json", ".yaml", ".docx"])


# ---------------------------------------------------------------------------
# cmd_experience_export (lines 541-560)
# ---------------------------------------------------------------------------


class TestCmdExperienceExportUnit(unittest.TestCase):
    """Unit tests for cmd_experience_export — data, resume, and error branches."""

    def _make_args(self, **overrides) -> MagicMock:
        args = MagicMock()
        args.data = "data.json"
        args.resume = None
        args.max_bullets = None
        args.out = "experience.yaml"
        args.out_dir = None
        args.profile = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.build_experience_summary", return_value={"jobs": []})
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test", "experience": []})
    def test_data_path_happy_path_returns_zero(
        self, mock_read, mock_overlay, mock_summary, mock_write
    ) -> None:
        from resume.cli.main import cmd_experience_export

        mock_overlay.return_value = {"name": "Test", "experience": []}
        args = self._make_args(data="data.json", resume=None)
        result = cmd_experience_export(args)
        self.assertEqual(result, 0)
        mock_write.assert_called_once()

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.build_experience_summary", return_value={"jobs": []})
    @patch("resume.cli.main.apply_profile_overlays")
    @patch("resume.cli.main.read_yaml_or_json", return_value={"name": "Test"})
    def test_data_path_applies_profile_overlay_when_set(
        self, mock_read, mock_overlay, mock_summary, mock_write
    ) -> None:
        from resume.cli.main import cmd_experience_export

        mock_overlay.return_value = {"name": "Test", "overlaid": True}
        args = self._make_args(data="data.json", resume=None, profile="myprofile")
        cmd_experience_export(args)
        mock_overlay.assert_called_once_with({"name": "Test"}, "myprofile")

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.build_experience_summary", return_value={"jobs": []})
    @patch("resume.cli.main.parse_resume_text", return_value={"experience": []})
    @patch("resume.cli.main.read_text_any", return_value="Resume text here")
    def test_resume_text_path_parses_and_returns_zero(
        self, mock_read_any, mock_parse, mock_summary, mock_write
    ) -> None:
        from resume.cli.main import cmd_experience_export

        args = self._make_args(data=None, resume="resume.txt")
        result = cmd_experience_export(args)
        self.assertEqual(result, 0)
        mock_parse.assert_called_once_with("Resume text here")
        mock_write.assert_called_once()

    @patch("resume.cli.main.write_yaml_or_json")
    @patch("resume.cli.main.build_experience_summary", return_value={"jobs": []})
    @patch("resume.cli.main.read_text_any", return_value="")
    def test_resume_docx_path_dispatches_to_parse_resume_docx(
        self, mock_read_any, mock_summary, mock_write
    ) -> None:
        """DOCX resume path uses parse_resume_docx (lazy import inside function body)."""
        from resume.cli.main import cmd_experience_export

        args = self._make_args(data=None, resume="resume.docx")
        # parse_resume_docx is imported lazily inside cmd_experience_export;
        # patch it where it is defined
        with patch("resume.parsing_experience_docx.parse_resume_docx", return_value={"experience": []}) as mock_docx:
            result = cmd_experience_export(args)
        self.assertEqual(result, 0)
        mock_docx.assert_called_once_with("resume.docx")

    def test_missing_data_and_resume_raises_system_exit(self) -> None:
        """Missing both --data and --resume exits non-zero."""
        from resume.cli.main import cmd_experience_export

        args = self._make_args(data=None, resume=None)
        with self.assertRaises(SystemExit) as ctx:
            cmd_experience_export(args)
        self.assertNotEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# cmd_export_pdf (lines 651-677)
# ---------------------------------------------------------------------------


class TestCmdExportPdfUnit(unittest.TestCase):
    """Unit tests for cmd_export_pdf — happy path + all sad paths."""

    def _make_args(self, docx_path: str, out: str | None = None, **overrides) -> MagicMock:
        args = MagicMock()
        args.docx = docx_path
        args.out = out
        args.profile = "sample"
        args.out_dir = None
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def test_missing_docx_raises_cli_error_usage(self) -> None:
        """A missing --docx file must raise CLIError with ExitCode.USAGE."""
        from core.cli_errors import CLIError, ExitCode
        from resume.cli.main import cmd_export_pdf

        args = self._make_args(docx_path="/nonexistent/path.docx", out="/tmp/out.pdf")  # nosec B108 - test path
        with self.assertRaises(CLIError) as ctx:
            cmd_export_pdf(args)
        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        self.assertIn("not found", str(ctx.exception))

    @patch("resume.australian_rotate.convert_docx_to_pdf", return_value=False)
    def test_failed_conversion_raises_cli_error_error(self, mock_convert) -> None:
        """A failed LibreOffice conversion must raise CLIError with ExitCode.ERROR."""
        from core.cli_errors import CLIError, ExitCode
        from resume.cli.main import cmd_export_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_bytes(b"fake docx content")
            out_path = os.path.join(tmpdir, "resume.pdf")
            args = self._make_args(docx_path=docx_path, out=out_path)
            with self.assertRaises(CLIError) as ctx:
                cmd_export_pdf(args)
        self.assertEqual(ctx.exception.code, ExitCode.ERROR)
        self.assertIn("LibreOffice", str(ctx.exception))

    @patch("resume.australian_rotate.convert_docx_to_pdf", return_value=True)
    def test_happy_path_prints_output_path_and_returns_zero(self, mock_convert) -> None:
        import io
        from contextlib import redirect_stdout
        from resume.cli.main import cmd_export_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_bytes(b"fake docx content")
            out_path = os.path.join(tmpdir, "resume.pdf")
            # Create the expected pdf output so rename logic doesn't fail
            Path(out_path).write_bytes(b"fake pdf")
            args = self._make_args(docx_path=docx_path, out=out_path)
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_export_pdf(args)
        self.assertEqual(result, 0)
        self.assertIn("resume.pdf", buf.getvalue())

    @patch("resume.australian_rotate.convert_docx_to_pdf", return_value=True)
    def test_actual_pdf_renamed_when_libreoffice_writes_different_path(self, mock_convert) -> None:
        """LibreOffice writes <stem>.pdf into outdir; if it differs from out_pdf it is renamed."""
        import io
        from contextlib import redirect_stdout
        from resume.cli.main import cmd_export_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "myresume.docx")
            Path(docx_path).write_bytes(b"fake docx content")

            # LibreOffice would write <stem>.pdf into outdir; simulate by pre-creating it
            # at the stem-derived name while requesting a different final output name.
            actual_pdf = os.path.join(tmpdir, "myresume.pdf")
            out_pdf = os.path.join(tmpdir, "myresume_final.pdf")

            Path(actual_pdf).write_bytes(b"converted pdf")
            args = self._make_args(docx_path=docx_path, out=out_pdf)
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_export_pdf(args)
            # Assertions must be inside the TemporaryDirectory block
            self.assertEqual(result, 0)
            self.assertTrue(Path(out_pdf).exists(), "Output PDF should exist at the requested path")
            self.assertFalse(Path(actual_pdf).exists(), "Intermediate PDF should have been renamed away")


if __name__ == "__main__":
    unittest.main()
