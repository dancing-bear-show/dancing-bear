"""Tests for the `resume docx-text` CLI command."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path


def _make_docx(tmp: Path, xml_body: str) -> Path:
    """Write a minimal .docx (zip) with the given word/document.xml content."""
    path = tmp / "test.docx"
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("word/document.xml", xml_body)
    return path


class TestDocxTextCommand(unittest.TestCase):
    """Unit tests for cmd_docx_text via the resume CLI main()."""

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        """Invoke resume CLI main() and capture stdout/stderr + return code."""
        from resume.cli.main import main

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = main(["docx-text"] + argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_extracts_text_from_valid_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = (
                "<w:document><w:body>"
                "<w:p><w:r><w:t>Hello &amp; World</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            path = _make_docx(Path(tmpdir), xml)
            rc, stdout, stderr = self._run([str(path)])
        self.assertEqual(rc, 0, msg=stderr)
        self.assertIn("Hello & World", stdout)

    def test_paragraph_break_becomes_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = (
                "<w:document><w:body>"
                "<w:p><w:r><w:t>Line one</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Line two</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            path = _make_docx(Path(tmpdir), xml)
            rc, stdout, _ = self._run([str(path)])
        self.assertEqual(rc, 0)
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        self.assertIn("Line one", lines[0])
        self.assertIn("Line two", lines[1])

    def test_missing_file_exits_nonzero_with_stderr(self) -> None:
        rc, stdout, stderr = self._run(["/nonexistent/path/to/file.docx"])
        self.assertNotEqual(rc, 0)
        self.assertIn("not found", stderr)
        self.assertEqual(stdout.strip(), "")

    def test_not_a_zip_exits_nonzero_with_stderr(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False, mode="wb") as f:
            f.write(b"this is not a zip file")
            fname = f.name
        try:
            rc, stdout, stderr = self._run([fname])
        finally:
            Path(fname).unlink(missing_ok=True)
        self.assertNotEqual(rc, 0)
        self.assertIn("not a valid", stderr)
        self.assertEqual(stdout.strip(), "")

    def test_zip_missing_document_xml_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nodoc.docx"
            with zipfile.ZipFile(str(path), "w") as zf:
                zf.writestr("word/styles.xml", "<styles/>")
            rc, _, stderr = self._run([str(path)])
        self.assertNotEqual(rc, 0)
        self.assertIn("word/document.xml", stderr)

    def test_html_entities_are_unescaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = (
                "<w:document><w:body>"
                "<w:p><w:r><w:t>A &lt;B&gt; &amp; C</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            path = _make_docx(Path(tmpdir), xml)
            rc, stdout, _ = self._run([str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("A <B> & C", stdout)


class TestDocxStructureMode(unittest.TestCase):
    """Tests for `docx-text --structure`, the layout-markup probe.

    resume-audit uses these counts to tell a genuine extraction failure from a
    document whose layout (tables, text boxes, columns) a paragraph walk was
    never going to read correctly.
    """

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        from resume.cli.main import main

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = main(["docx-text"] + argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_counts_tables_textboxes_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = (
                "<w:document><w:body>"
                "<w:tbl>a</w:tbl><w:tbl>b</w:tbl>"
                "<w:txbxContent>x</w:txbxContent>"
                "<w:cols/>"
                "</w:body></w:document>"
            )
            path = _make_docx(Path(tmpdir), xml)
            rc, out, _ = self._run(["--structure", str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("tables: 2", out)
        self.assertIn("textboxes: 1", out)
        self.assertIn("columns: 1", out)

    def test_reports_zero_for_a_plain_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = "<w:document><w:body><w:p><w:t>plain</w:t></w:p></w:body></w:document>"
            path = _make_docx(Path(tmpdir), xml)
            rc, out, _ = self._run(["--structure", str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("tables: 0", out)
        self.assertIn("textboxes: 0", out)

    def test_lists_header_and_footer_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.docx"
            with zipfile.ZipFile(str(path), "w") as zf:
                zf.writestr("word/document.xml", "<w:document/>")
                zf.writestr("word/header1.xml", "h")
                zf.writestr("word/footer1.xml", "f")
            rc, out, _ = self._run(["--structure", str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("header1.xml", out)
        self.assertIn("footer1.xml", out)

    def test_structure_mode_does_not_print_document_text(self) -> None:
        """--structure replaces the text dump; it must not emit both."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = (
                "<w:document><w:body>"
                "<w:p><w:t>SECRET_BODY_TEXT</w:t></w:p>"
                "</w:body></w:document>"
            )
            path = _make_docx(Path(tmpdir), xml)
            rc, out, _ = self._run(["--structure", str(path)])
        self.assertEqual(rc, 0)
        self.assertNotIn("SECRET_BODY_TEXT", out)

    def test_missing_file_reports_error(self) -> None:
        rc, _, err = self._run(["--structure", "/nonexistent/nope.docx"])
        self.assertEqual(rc, 1)
        self.assertIn("file not found", err)


class TestDocxNonUtf8Body(unittest.TestCase):
    """A DOCX body is UTF-8 by convention, not by guarantee.

    Rejecting a readable document over one stray byte would be worse than
    decoding it approximately, so the command falls back to latin-1 and says
    so on stderr rather than failing.
    """

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        from resume.cli.main import main

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = main(["docx-text"] + argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def _make_latin1_docx(self, tmp: Path) -> Path:
        path = tmp / "latin1.docx"
        body = "<w:document><w:body><w:p><w:t>caf\xe9</w:t></w:p></w:body></w:document>"
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("word/document.xml", body.encode("latin-1"))
        return path

    def test_latin1_body_does_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_latin1_docx(Path(tmpdir))
            rc, out, err = self._run([str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("café", out)
        self.assertIn("not valid UTF-8", err)

    def test_structure_mode_also_survives_latin1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._make_latin1_docx(Path(tmpdir))
            rc, out, _ = self._run(["--structure", str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("tables: 0", out)

    def test_utf8_body_emits_no_encoding_warning(self) -> None:
        """The fallback must stay silent on well-formed input."""
        with tempfile.TemporaryDirectory() as tmpdir:
            xml = "<w:document><w:body><w:t>café</w:t></w:body></w:document>"
            path = Path(tmpdir) / "utf8.docx"
            with zipfile.ZipFile(str(path), "w") as zf:
                zf.writestr("word/document.xml", xml.encode("utf-8"))
            rc, out, err = self._run([str(path)])
        self.assertEqual(rc, 0)
        self.assertIn("café", out)
        self.assertNotIn("not valid UTF-8", err)
