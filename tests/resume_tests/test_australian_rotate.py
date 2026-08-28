"""Tests for resume/australian_rotate.py — PDF rotation tool."""

from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open


class TestConvertDocxToPdf(unittest.TestCase):
    """Tests for convert_docx_to_pdf."""

    def test_returns_truthy_on_success(self):
        from resume.australian_rotate import convert_docx_to_pdf

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            # LibreOffice's output file must exist for the conversion to count
            # as a success; patching is_file stands in for it being written.
            with patch.object(Path, "is_file", lambda _self: True):
                result = convert_docx_to_pdf("/tmp/test.docx", "/tmp/test.pdf")  # nosec B108
        self.assertTrue(result)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("soffice", args)
        self.assertIn("--headless", args)
        self.assertIn("/tmp/test.docx", args)  # nosec B108 - test-only temp file, not a security concern

    def test_returns_falsy_on_nonzero_returncode(self):
        from resume.australian_rotate import ConversionFailure, convert_docx_to_pdf

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = convert_docx_to_pdf("/tmp/test.docx", "/tmp/test.pdf")  # nosec B108
        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_ERROR)

    def test_returns_falsy_when_zero_exit_writes_no_pdf(self):
        """LibreOffice can exit 0 without producing a file; that is not success."""
        from resume.australian_rotate import ConversionFailure, convert_docx_to_pdf

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            with patch.object(Path, "is_file", lambda _self: False):
                result = convert_docx_to_pdf("/tmp/test.docx", "/tmp/test.pdf")  # nosec B108
        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.NO_OUTPUT)

    def test_returns_falsy_on_timeout(self):
        from resume.australian_rotate import ConversionFailure, convert_docx_to_pdf
        import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("soffice", 30)):
            result = convert_docx_to_pdf("/tmp/test.docx", "/tmp/test.pdf")  # nosec B108
        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_TIMEOUT)

    def test_returns_falsy_on_file_not_found(self):
        from resume.australian_rotate import ConversionFailure, convert_docx_to_pdf

        with patch("subprocess.run", side_effect=FileNotFoundError("soffice not found")):
            result = convert_docx_to_pdf("/tmp/test.docx", "/tmp/test.pdf")  # nosec B108
        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_MISSING)

    def test_uses_correct_outdir(self):
        from resume.australian_rotate import convert_docx_to_pdf

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            convert_docx_to_pdf("/some/dir/test.docx", "/out/dir/test.pdf")  # nosec B108
        args = mock_run.call_args[0][0]
        # outdir should be the parent of the pdf_path
        outdir_idx = args.index("--outdir")
        self.assertEqual(args[outdir_idx + 1], "/out/dir")


class TestRotatePdf180(unittest.TestCase):
    """Tests for rotate_pdf_180."""

    def _make_mock_pypdf(self):
        """Build a mock pypdf module with PdfReader/PdfWriter."""
        mock_page = MagicMock()
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_writer = MagicMock()

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader
        mock_pypdf.PdfWriter.return_value = mock_writer
        return mock_pypdf, mock_reader, mock_writer, mock_page

    def test_returns_true_on_success(self):
        from resume.australian_rotate import rotate_pdf_180

        mock_pypdf, _mock_reader, mock_writer, mock_page = self._make_mock_pypdf()
        with patch.dict("sys.modules", {"pypdf": mock_pypdf}):
            m = mock_open()
            with patch("builtins.open", m):
                result = rotate_pdf_180("/tmp/input.pdf", "/tmp/output.pdf")  # nosec B108
        self.assertTrue(result)
        mock_page.rotate.assert_called_once_with(180)
        mock_writer.add_page.assert_called_once_with(mock_page)
        mock_writer.write.assert_called_once()

    def test_returns_false_when_pypdf_missing(self):
        from resume.australian_rotate import rotate_pdf_180

        # Simulate both pypdf and PyPDF2 missing by setting them to None in sys.modules
        # which causes ImportError when `from pypdf import ...` is attempted
        with patch.dict("sys.modules", {"pypdf": None, "PyPDF2": None}):
            result = rotate_pdf_180("/tmp/input.pdf", "/tmp/output.pdf")  # nosec B108
        self.assertFalse(result)

    def test_returns_false_on_read_exception(self):
        from resume.australian_rotate import rotate_pdf_180

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.side_effect = Exception("corrupted PDF")
        with patch.dict("sys.modules", {"pypdf": mock_pypdf}):
            result = rotate_pdf_180("/tmp/input.pdf", "/tmp/output.pdf")  # nosec B108
        self.assertFalse(result)

    def test_rotates_multiple_pages(self):
        from resume.australian_rotate import rotate_pdf_180

        pages = [MagicMock(), MagicMock(), MagicMock()]
        mock_reader = MagicMock()
        mock_reader.pages = pages
        mock_writer = MagicMock()

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader
        mock_pypdf.PdfWriter.return_value = mock_writer

        with patch.dict("sys.modules", {"pypdf": mock_pypdf}):
            m = mock_open()
            with patch("builtins.open", m):
                result = rotate_pdf_180("/tmp/input.pdf", "/tmp/output.pdf")  # nosec B108

        self.assertTrue(result)
        for page in pages:
            page.rotate.assert_called_once_with(180)
        self.assertEqual(mock_writer.add_page.call_count, 3)


def _converted(pdf_path: str):
    """A successful ConversionResult naming *pdf_path* as LibreOffice's output."""
    from resume.australian_rotate import ConversionResult

    return ConversionResult(ok=True, pdf_path=Path(pdf_path))


class TestCreateAustralianResume(unittest.TestCase):
    """Tests for create_australian_resume."""

    def test_returns_none_when_docx_missing(self):
        from resume.australian_rotate import create_australian_resume

        result = create_australian_resume("/nonexistent/path/resume.docx")
        self.assertIsNone(result)

    def test_returns_none_when_conversion_fails(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:  # nosec B108 - test-only temp file, not a security concern
            docx_path = tf.name
        try:
            from resume.australian_rotate import ConversionFailure, ConversionResult

            failure = ConversionResult(
                ok=False, failure=ConversionFailure.CONVERTER_MISSING
            )
            with patch("resume.australian_rotate.convert_docx_to_pdf", return_value=failure):
                result = create_australian_resume(docx_path)
            self.assertIsNone(result)
        finally:
            os.unlink(docx_path)

    def test_returns_none_when_no_pdf_was_written(self):
        """A converter that exits 0 without writing a PDF must abort the render.

        This used to be caught by a redundant existence check in this function
        after the converter had already reported success.  The check now lives
        in the converter itself, so the caller sees an ordinary falsy result.
        """
        from resume.australian_rotate import (
            ConversionFailure,
            ConversionResult,
            create_australian_resume,
        )

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:  # nosec B108 - test-only temp file, not a security concern
            docx_path = tf.name
        try:
            no_output = ConversionResult(ok=False, failure=ConversionFailure.NO_OUTPUT)
            with patch(
                "resume.australian_rotate.convert_docx_to_pdf", return_value=no_output
            ):
                with patch("resume.australian_rotate.rotate_pdf_180") as rotate:
                    result = create_australian_resume(docx_path)
            self.assertIsNone(result)
            rotate.assert_not_called()
        finally:
            os.unlink(docx_path)

    def test_returns_output_path_on_success(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")
            out_pdf = os.path.join(tmpdir, "resume.australian.pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(temp_pdf),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                    result = create_australian_resume(docx_path, output_pdf=out_pdf)

            self.assertEqual(result, out_pdf)

    def test_cleans_up_temp_file_by_default(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")
            out_pdf = os.path.join(tmpdir, "resume.australian.pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(temp_pdf),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                    create_australian_resume(docx_path, output_pdf=out_pdf)

            self.assertFalse(Path(temp_pdf).exists())

    def test_keeps_temp_file_when_requested(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")
            out_pdf = os.path.join(tmpdir, "resume.australian.pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(temp_pdf),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                    create_australian_resume(docx_path, output_pdf=out_pdf, keep_temp=True)

            self.assertTrue(Path(temp_pdf).exists())

    def test_default_output_pdf_path(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(temp_pdf),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                    result = create_australian_resume(docx_path)

            expected = os.path.join(tmpdir, "resume.australian.pdf")
            self.assertEqual(result, expected)

    def test_returns_none_when_rotation_fails(self):
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")
            out_pdf = os.path.join(tmpdir, "resume.australian.pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(temp_pdf),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=False):
                    result = create_australian_resume(docx_path, output_pdf=out_pdf)

            self.assertIsNone(result)

    def test_handles_libreoffice_output_rename(self):
        """LibreOffice outputs to same dir with .pdf ext — tests rename logic."""
        from resume.australian_rotate import create_australian_resume

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            # LibreOffice creates resume.pdf (not resume.temp.pdf)
            actual_temp = os.path.join(tmpdir, "resume.pdf")
            Path(actual_temp).write_text("fake pdf")
            out_pdf = os.path.join(tmpdir, "resume.australian.pdf")

            with patch(
                "resume.australian_rotate.convert_docx_to_pdf",
                return_value=_converted(actual_temp),
            ):
                with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                    result = create_australian_resume(docx_path, output_pdf=out_pdf)

            self.assertEqual(result, out_pdf)
            # The LibreOffice-named file was renamed to the intermediate path.
            self.assertFalse(Path(actual_temp).exists())


class TestMain(unittest.TestCase):
    """Tests for CLI entry point."""

    def test_main_returns_1_on_failure(self):
        from resume.australian_rotate import main

        with patch("sys.argv", ["australian_rotate", "/nonexistent/file.docx"]):
            exit_code = main()
        self.assertEqual(exit_code, 1)

    def test_main_returns_0_on_success(self):
        from resume.australian_rotate import main

        with tempfile.TemporaryDirectory() as tmpdir:  # nosec B108 - test-only temp file, not a security concern
            docx_path = os.path.join(tmpdir, "resume.docx")
            Path(docx_path).write_text("fake docx")
            temp_pdf = os.path.join(tmpdir, "resume.temp.pdf")
            Path(temp_pdf).write_text("fake pdf")

            with patch("sys.argv", ["australian_rotate", docx_path]):
                with patch(
                    "resume.australian_rotate.convert_docx_to_pdf",
                    return_value=_converted(temp_pdf),
                ):
                    with patch("resume.australian_rotate.rotate_pdf_180", return_value=True):
                        exit_code = main()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
