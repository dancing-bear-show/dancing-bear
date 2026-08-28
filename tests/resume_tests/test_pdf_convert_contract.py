"""Contract tests for the DOCX -> PDF conversion path.

Covers ``resume.australian_rotate.convert_docx_to_pdf`` and
``resume.cli.main.cmd_export_pdf``.

These tests NEVER invoke a real ``soffice`` binary.  Every test either patches
``subprocess.run`` (for the converter) or patches ``convert_docx_to_pdf`` itself
(for the CLI command), so the whole module passes on a machine with no
LibreOffice installed -- which is what CI is.  A test that only passes where
``soffice`` happens to exist is a flake, not coverage.

Focus is the contract that existing tests do not pin:

  * argv is built as a **list**, never a shell string, and every element is
    passed through untouched -- the injection guard.  This matters most for
    paths containing spaces, quotes and unicode.
  * ordering: a missing source DOCX is rejected **before** the converter is
    ever invoked.
  * the ``CLIError`` *content* (message and hint), not merely its type.
  * the rename branch is skipped when LibreOffice's output path already equals
    the requested ``--out``.

It also pins a real defect -- see ``TestExportPdfSucceedsWithoutWritingFile``.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess  # nosec B404 - imported only to reference TimeoutExpired in patches
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cli_errors import CLIError, ExitCode
from resume.australian_rotate import convert_docx_to_pdf
from resume.cli.main import cmd_export_pdf


@dataclass(frozen=True)
class ConvertCall:
    """The decomposed argv of a single ``convert_docx_to_pdf`` subprocess call."""

    argv: list[str]

    @property
    def outdir(self) -> str:
        return self.argv[self.argv.index("--outdir") + 1]

    @property
    def docx(self) -> str:
        """The input path -- always the final positional element."""
        return self.argv[-1]


def _fake_run(returncode: int = 0) -> MagicMock:
    """Build a ``subprocess.run`` stand-in returning *returncode*."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = ""
    result.stderr = ""
    return MagicMock(return_value=result)


def _capture_convert(docx_path: str, pdf_path: str, *, returncode: int = 0) -> tuple[bool, ConvertCall]:
    """Run the converter against a patched subprocess and return (result, call)."""
    runner = _fake_run(returncode)
    with patch("resume.australian_rotate.subprocess.run", runner):
        ok = convert_docx_to_pdf(docx_path, pdf_path)
    runner.assert_called_once()
    return ok, ConvertCall(list(runner.call_args[0][0]))


def _export_args(docx: str, out: str | None, out_dir: str | None = None) -> argparse.Namespace:
    """Build the exact Namespace ``cmd_export_pdf`` reads.

    A real Namespace (not a MagicMock) is used deliberately: MagicMock makes
    every attribute truthy, which would mask a bug where ``_resolve_out``
    consults an attribute this command never sets.
    """
    return argparse.Namespace(docx=docx, out=out, profile=None, out_dir=out_dir)


class TestConvertArgvIsAList(unittest.TestCase):
    """The converter must hand subprocess a list, never a shell string."""

    def test_argv_is_a_list_of_strings_with_shell_disabled(self) -> None:
        runner = _fake_run(0)
        with patch("resume.australian_rotate.subprocess.run", runner):
            convert_docx_to_pdf("/in/resume.docx", "/out/resume.pdf")

        argv = runner.call_args[0][0]
        self.assertIsInstance(argv, list)
        for element in argv:
            self.assertIsInstance(element, str)
        # shell=True would reintroduce the injection surface the list form avoids.
        self.assertNotIn("shell", runner.call_args.kwargs)

    def test_argv_carries_the_expected_libreoffice_invocation(self) -> None:
        _ok, call = _capture_convert("/in/resume.docx", "/out/resume.pdf")

        self.assertEqual(
            call.argv,
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                "/out",
                "/in/resume.docx",
            ],
        )

    def test_run_is_bounded_by_a_timeout_and_captures_output(self) -> None:
        runner = _fake_run(0)
        with patch("resume.australian_rotate.subprocess.run", runner):
            convert_docx_to_pdf("/in/resume.docx", "/out/resume.pdf")

        kwargs = runner.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 30)
        self.assertTrue(kwargs["capture_output"])


class TestConvertOutdirIsParent(unittest.TestCase):
    """``--outdir`` receives the parent directory, never the PDF path itself."""

    def test_outdir_is_the_parent_of_the_requested_pdf(self) -> None:
        _ok, call = _capture_convert("/in/resume.docx", "/out/nested/final.pdf")

        self.assertEqual(call.outdir, "/out/nested")
        self.assertNotIn("/out/nested/final.pdf", call.argv)

    def test_outdir_for_a_bare_filename_is_the_current_directory(self) -> None:
        _ok, call = _capture_convert("resume.docx", "resume.pdf")

        self.assertEqual(call.outdir, ".")


class TestConvertReturnsBool(unittest.TestCase):
    """The converter collapses every outcome to a bool."""

    def test_returns_true_on_zero_exit(self) -> None:
        ok, _call = _capture_convert("/in/a.docx", "/out/a.pdf", returncode=0)

        self.assertIs(ok, True)

    def test_invalid_nonzero_exit_returns_false(self) -> None:
        ok, _call = _capture_convert("/in/a.docx", "/out/a.pdf", returncode=3)

        self.assertIs(ok, False)

    def test_invalid_missing_soffice_binary_returns_false(self) -> None:
        """No ``soffice`` on PATH: FileNotFoundError is swallowed, no traceback."""
        with patch(
            "resume.australian_rotate.subprocess.run",
            side_effect=FileNotFoundError(2, "No such file or directory", "soffice"),
        ):
            ok = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertIs(ok, False)

    def test_invalid_timeout_returns_false_without_hanging(self) -> None:
        with patch(
            "resume.australian_rotate.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=30),
        ):
            ok = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertIs(ok, False)

    def test_invalid_other_oserror_is_not_swallowed(self) -> None:
        """Only TimeoutExpired and FileNotFoundError are caught.

        A PermissionError propagates -- pinned so that widening the except
        clause becomes a deliberate, visible change rather than a silent one.
        """
        with patch(
            "resume.australian_rotate.subprocess.run",
            side_effect=PermissionError(13, "Permission denied", "soffice"),
        ):
            with self.assertRaises(PermissionError):
                convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")


class TestConvertPassesHostilePathsThrough(unittest.TestCase):
    """Paths with shell metacharacters reach argv verbatim -- no interpolation."""

    HOSTILE_STEMS = [
        "my resume 2024",
        "resume 'quoted'",
        'resume "double"',
        "resume;rm -rf tmp",
        "resume$(whoami)",
        "resume`id`",
        "resume&&echo pwned",
        "résumé-ünicode-简历",
        "resume|tee out",
    ]

    def test_hostile_stems_reach_argv_untouched(self) -> None:
        for stem in self.HOSTILE_STEMS:
            with self.subTest(stem=stem):
                docx = f"/in/{stem}.docx"
                pdf = f"/out dir/{stem}.pdf"
                _ok, call = _capture_convert(docx, pdf)

                # Exact element identity: no quoting added, nothing stripped,
                # and no element was split on a space or a metacharacter.
                self.assertEqual(call.docx, docx)
                self.assertEqual(call.outdir, "/out dir")
                self.assertEqual(len(call.argv), 7)

    def test_a_path_with_spaces_stays_one_argv_element(self) -> None:
        _ok, call = _capture_convert("/in/my resume.docx", "/out/my resume.pdf")

        self.assertIn("/in/my resume.docx", call.argv)
        # The split-on-space failure mode would produce these fragments.
        self.assertNotIn("/in/my", call.argv)
        self.assertNotIn("resume.docx", call.argv)


class TestExportPdfHappyPath(unittest.TestCase):
    """``cmd_export_pdf`` success paths."""

    def test_renames_libreoffice_output_to_the_requested_out(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "myresume.docx")
            docx.write_bytes(b"fake docx")
            written_by_soffice = Path(td, "myresume.pdf")
            requested = Path(td, "final-name.pdf")

            def fake_convert(_docx: str, _pdf: str) -> bool:
                written_by_soffice.write_bytes(b"%PDF-1.4 fake")
                return True

            with patch("resume.australian_rotate.convert_docx_to_pdf", fake_convert):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cmd_export_pdf(_export_args(str(docx), str(requested)))

            self.assertEqual(rc, 0)
            self.assertTrue(requested.exists())
            self.assertFalse(written_by_soffice.exists())
            self.assertEqual(buf.getvalue().strip(), str(requested))

    def test_does_not_rename_when_output_already_matches_requested_path(self) -> None:
        """``--out`` equal to ``<stem>.pdf``: the rename branch must not fire."""
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "myresume.docx")
            docx.write_bytes(b"fake docx")
            requested = Path(td, "myresume.pdf")  # identical to LibreOffice's own name

            def fake_convert(_docx: str, _pdf: str) -> bool:
                requested.write_bytes(b"%PDF-1.4 fake")
                return True

            with patch("resume.australian_rotate.convert_docx_to_pdf", fake_convert):
                with patch.object(Path, "rename", side_effect=AssertionError("rename must not run")):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = cmd_export_pdf(_export_args(str(docx), str(requested)))

            self.assertEqual(rc, 0)
            self.assertEqual(requested.read_bytes(), b"%PDF-1.4 fake")
            self.assertEqual(buf.getvalue().strip(), str(requested))

    def test_creates_missing_parent_directories_for_the_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "myresume.docx")
            docx.write_bytes(b"fake docx")
            requested = Path(td, "deeply", "nested", "out.pdf")

            def fake_convert(_docx: str, pdf: str) -> bool:
                # The parent must already exist by the time the converter runs,
                # since LibreOffice writes into it via --outdir.
                self.assertTrue(Path(pdf).parent.is_dir())
                Path(Path(pdf).parent, "myresume.pdf").write_bytes(b"%PDF-1.4")
                return True

            with patch("resume.australian_rotate.convert_docx_to_pdf", fake_convert):
                with redirect_stdout(io.StringIO()):
                    rc = cmd_export_pdf(_export_args(str(docx), str(requested)))

            self.assertEqual(rc, 0)
            self.assertTrue(requested.exists())

    def test_passes_the_source_docx_through_to_the_converter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "source name.docx")
            docx.write_bytes(b"fake docx")
            requested = Path(td, "out.pdf")

            convert = MagicMock(return_value=True)
            with patch("resume.australian_rotate.convert_docx_to_pdf", convert):
                with redirect_stdout(io.StringIO()):
                    cmd_export_pdf(_export_args(str(docx), str(requested)))

            convert.assert_called_once_with(str(docx), str(requested))


class TestExportPdfSadPaths(unittest.TestCase):
    """``cmd_export_pdf`` failure paths, asserted on message content."""

    def test_invalid_conversion_failure_names_libreoffice_in_message_and_hint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "resume.docx")
            docx.write_bytes(b"fake docx")

            with patch("resume.australian_rotate.convert_docx_to_pdf", return_value=False):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(docx), str(Path(td, "out.pdf"))))

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.ERROR)
        self.assertIn("LibreOffice", err.message)
        self.assertIn("conversion failed", err.message.lower())
        self.assertIsNotNone(err.hint)
        self.assertIn("install", err.hint.lower())
        self.assertIn("soffice", err.hint)

    def test_rejects_missing_docx_before_invoking_the_converter(self) -> None:
        """Ordering is the point: the existence check gates the subprocess.

        Both the converter and ``subprocess.run`` are asserted un-called, so
        this fails loudly if the check is ever moved below the conversion.
        """
        with tempfile.TemporaryDirectory() as td:
            absent = Path(td, "ghost.docx")

            convert = MagicMock(return_value=True)
            runner = _fake_run(0)
            with patch("resume.australian_rotate.convert_docx_to_pdf", convert):
                with patch("resume.australian_rotate.subprocess.run", runner):
                    with self.assertRaises(CLIError) as ctx:
                        cmd_export_pdf(_export_args(str(absent), str(Path(td, "out.pdf"))))

        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        self.assertIn("file not found", ctx.exception.message)
        self.assertIn(str(absent), ctx.exception.message)
        convert.assert_not_called()
        runner.assert_not_called()

    def test_rejects_a_directory_passed_as_docx(self) -> None:
        """``is_file()`` -- not ``exists()`` -- so a directory is rejected too."""
        with tempfile.TemporaryDirectory() as td:
            a_dir = Path(td, "notafile.docx")
            a_dir.mkdir()

            convert = MagicMock(return_value=True)
            with patch("resume.australian_rotate.convert_docx_to_pdf", convert):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(a_dir), str(Path(td, "out.pdf"))))

        self.assertEqual(ctx.exception.code, ExitCode.USAGE)
        convert.assert_not_called()

    def test_rejects_pdf_output_from_render_and_points_at_export_pdf(self) -> None:
        """``render --out x.pdf`` must emit the current message, not the old one.

        The superseded wording promised the feature was "planned for future";
        the documented behaviour is to redirect the user to ``export-pdf``.
        """
        from resume.cli.main import cmd_render

        args = argparse.Namespace(
            out="resume.pdf",
            out_dir=None,
            profile=None,
            data=None,
            template=None,
            seed=None,
            style_profile=None,
            min_priority=None,
            structure=None,
        )
        with patch("resume.cli.main._load_candidate_data", return_value={"name": "T"}):
            with patch("resume.cli.main.load_template", return_value={}):
                with patch("resume.cli.main._apply_filter_pipeline", return_value={"name": "T"}):
                    with patch("resume.cli.main._load_structure", return_value=None):
                        with self.assertRaises(CLIError) as ctx:
                            cmd_render(args)

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.USAGE)
        self.assertIn("export-pdf", err.message)
        self.assertIn(".docx only", err.message)
        self.assertNotIn("planned for future", err.message)


class TestExportPdfSucceedsWithoutWritingFile(unittest.TestCase):
    """PINNED DEFECT -- current behaviour, deliberately not fixed here.

    ``convert_docx_to_pdf`` returns ``result.returncode == 0`` and discards
    stderr.  LibreOffice can exit 0 without producing a PDF (an unreadable
    input, a full or read-only outdir).  ``cmd_export_pdf`` then finds
    ``actual.exists()`` false, skips the rename silently, prints the requested
    path, and returns 0.

    The caller is handed exit 0 and a path to a file that does not exist.  A
    downstream step that trusts the exit code fails later and further away
    from the cause.

    These tests pin the behaviour as it stands so the defect is visible and a
    future fix has a failing test to flip.  Fixing it is a ``src/`` change and
    belongs in its own PR.
    """

    def _run_with_silent_success(self, td: str) -> tuple[int, str, Path]:
        docx = Path(td, "resume.docx")
        docx.write_bytes(b"fake docx")
        requested = Path(td, "final.pdf")

        # Converter reports success but writes nothing -- exactly what
        # `returncode == 0` with no output file looks like.
        with patch("resume.australian_rotate.convert_docx_to_pdf", return_value=True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cmd_export_pdf(_export_args(str(docx), str(requested)))
        return rc, buf.getvalue().strip(), requested

    def test_invalid_zero_exit_reported_although_no_pdf_was_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rc, _printed, requested = self._run_with_silent_success(td)

            self.assertEqual(rc, 0, "current behaviour: success is reported")
            self.assertFalse(
                requested.exists(),
                "current behaviour: no PDF exists despite the zero exit",
            )

    def test_invalid_prints_a_path_to_a_file_that_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _rc, printed, requested = self._run_with_silent_success(td)

            self.assertEqual(printed, str(requested))
            self.assertFalse(Path(printed).exists())

    def test_invalid_leaves_the_output_directory_without_any_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self._run_with_silent_success(td)

            self.assertEqual(
                sorted(p.name for p in Path(td).iterdir()),
                ["resume.docx"],
                "current behaviour: outdir holds only the input",
            )

    def test_invalid_converter_reports_success_without_checking_output(self) -> None:
        """The root cause, at the converter level: the file is never checked."""
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td, "never-written.pdf")
            ok, _call = _capture_convert(str(Path(td, "a.docx")), str(pdf), returncode=0)

            self.assertIs(ok, True)
            self.assertFalse(pdf.exists())


class TestConversionNeverShellsOut(unittest.TestCase):
    """Guard: this module must not depend on a real LibreOffice install."""

    def test_no_real_soffice_is_invoked_when_subprocess_is_patched(self) -> None:
        """A patched runner intercepts the call, so PATH is never consulted."""
        runner = _fake_run(0)
        with patch("resume.australian_rotate.subprocess.run", runner):
            ok = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertIs(ok, True)
        runner.assert_called_once()
        self.assertEqual(runner.call_args[0][0][0], "soffice")

    def test_invalid_scrubbed_path_still_yields_false_not_an_exception(self) -> None:
        """Even with no PATH at all the converter degrades to False.

        ``subprocess.run`` is still patched, so nothing is executed; this pins
        that the no-binary outcome is a clean ``False``.
        """
        with patch.dict(os.environ, {"PATH": ""}, clear=False):
            with patch(
                "resume.australian_rotate.subprocess.run",
                side_effect=FileNotFoundError(2, "No such file or directory", "soffice"),
            ):
                ok = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertIs(ok, False)


if __name__ == "__main__":
    unittest.main()
