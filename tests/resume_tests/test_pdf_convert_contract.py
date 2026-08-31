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

The zero-exit-but-no-file case is covered by
``TestConverterRequiresAnOutputFile`` and
``TestExportPdfFailsLoudlyWhenNoPdfIsWritten``.
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
from resume.australian_rotate import (
    ConversionFailure,
    ConversionResult,
    convert_docx_to_pdf,
)
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


def _fake_run(returncode: int = 0, stderr: str = "") -> MagicMock:
    """Build a ``subprocess.run`` stand-in returning *returncode* and *stderr*."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = ""
    result.stderr = stderr
    return MagicMock(return_value=result)


def _capture_convert(
    docx_path: str,
    pdf_path: str,
    *,
    returncode: int = 0,
    stderr: str = "",
    writes_output: bool = True,
) -> tuple[ConversionResult, ConvertCall]:
    """Run the converter against a patched subprocess and return (result, call).

    The converter now requires LibreOffice's output file to exist on disk, so
    the patched runner stands in for that side effect.  ``writes_output=False``
    reproduces the exit-0-but-no-file case.  ``Path.is_file`` is patched rather
    than touching the filesystem, which keeps the argv-inspection tests free to
    use non-existent paths like ``/in/resume.docx``.
    """
    runner = _fake_run(returncode, stderr)
    with patch("resume.australian_rotate.subprocess.run", runner):
        with patch.object(Path, "is_file", lambda _self: writes_output):
            result = convert_docx_to_pdf(docx_path, pdf_path)
    runner.assert_called_once()
    return result, ConvertCall(list(runner.call_args[0][0]))


def _ok_result(pdf: Path) -> ConversionResult:
    """A successful ConversionResult naming *pdf* as the file LibreOffice wrote."""
    return ConversionResult(ok=True, pdf_path=pdf)


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


class TestConvertResultTruthiness(unittest.TestCase):
    """Every outcome is a ConversionResult whose truthiness is the success test.

    ``convert_docx_to_pdf`` used to return a bare ``bool``.  It now returns a
    ConversionResult that stays falsy on failure -- so the two callers, which
    both branch on falsiness, are unaffected -- while carrying *why* the
    conversion failed.  These tests assert both halves: the truthiness the
    callers depend on, and the reason that lets them report it accurately.
    """

    def test_zero_exit_with_output_file_is_truthy(self) -> None:
        result, _call = _capture_convert("/in/a.docx", "/out/a.pdf", returncode=0)

        self.assertTrue(result)
        self.assertIs(result.ok, True)
        self.assertIs(result.failure, ConversionFailure.NONE)

    def test_invalid_nonzero_exit_is_falsy(self) -> None:
        result, _call = _capture_convert("/in/a.docx", "/out/a.pdf", returncode=3)

        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_ERROR)

    def test_invalid_missing_soffice_binary_is_falsy(self) -> None:
        """No ``soffice`` on PATH: FileNotFoundError is swallowed, no traceback."""
        with patch(
            "resume.australian_rotate.subprocess.run",
            side_effect=FileNotFoundError(2, "No such file or directory", "soffice"),
        ):
            result = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_MISSING)

    def test_invalid_timeout_is_falsy_without_hanging(self) -> None:
        with patch(
            "resume.australian_rotate.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=30),
        ):
            result = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_TIMEOUT)

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

    def test_each_failure_mode_has_a_distinct_message(self) -> None:
        """The whole point of the typed result: the modes are distinguishable."""
        failures = [
            ConversionFailure.CONVERTER_MISSING,
            ConversionFailure.CONVERTER_TIMEOUT,
            ConversionFailure.CONVERTER_ERROR,
            ConversionFailure.NO_OUTPUT,
        ]
        messages = [ConversionResult(ok=False, failure=f).message for f in failures]

        self.assertEqual(len(set(messages)), len(failures))
        for message in messages:
            self.assertTrue(message.strip())

    def test_a_successful_result_reports_the_pdf_it_verified(self) -> None:
        result, _call = _capture_convert("/in/a.docx", "/out/renamed.pdf")

        # LibreOffice names its output after the *docx* stem, not the request.
        self.assertEqual(result.pdf_path, Path("/out/a.pdf"))


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

            def fake_convert(_docx: str, _pdf: str) -> ConversionResult:
                written_by_soffice.write_bytes(b"%PDF-1.4 fake")
                return _ok_result(written_by_soffice)

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

            def fake_convert(_docx: str, _pdf: str) -> ConversionResult:
                requested.write_bytes(b"%PDF-1.4 fake")
                return _ok_result(requested)

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

            def fake_convert(_docx: str, pdf: str) -> ConversionResult:
                # The parent must already exist by the time the converter runs,
                # since LibreOffice writes into it via --outdir.
                self.assertTrue(Path(pdf).parent.is_dir())
                produced = Path(Path(pdf).parent, "myresume.pdf")
                produced.write_bytes(b"%PDF-1.4")
                return _ok_result(produced)

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

            convert = MagicMock(return_value=_ok_result(requested))
            with patch("resume.australian_rotate.convert_docx_to_pdf", convert):
                with redirect_stdout(io.StringIO()):
                    cmd_export_pdf(_export_args(str(docx), str(requested)))

            convert.assert_called_once_with(str(docx), str(requested))


class TestExportPdfSadPaths(unittest.TestCase):
    """``cmd_export_pdf`` failure paths, asserted on message content."""

    def test_invalid_conversion_failure_names_libreoffice_in_message_and_hint(self) -> None:
        """The missing-binary mode keeps the install message and hint."""
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "resume.docx")
            docx.write_bytes(b"fake docx")
            failure = ConversionResult(
                ok=False, failure=ConversionFailure.CONVERTER_MISSING
            )

            with patch("resume.australian_rotate.convert_docx_to_pdf", return_value=failure):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(docx), str(Path(td, "out.pdf"))))

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.ERROR)
        self.assertIn("LibreOffice", err.message)
        self.assertIn("conversion failed", err.message.lower())
        self.assertIsNotNone(err.hint)
        assert err.hint is not None  # nosec B101 - type narrowing for mypy
        self.assertIn("install", err.hint.lower())
        self.assertIn("soffice", err.hint)

    def test_invalid_nonzero_exit_reports_a_converter_error_not_a_missing_binary(
        self,
    ) -> None:
        """A LibreOffice that ran and failed is not a LibreOffice that is absent."""
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "resume.docx")
            docx.write_bytes(b"fake docx")

            runner = _fake_run(3, stderr="Error: cannot open input")
            with patch("resume.australian_rotate.subprocess.run", runner):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(docx), str(Path(td, "out.pdf"))))

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.ERROR)
        self.assertIn("exited with an error", err.message)
        self.assertIn("cannot open input", err.message)
        self.assertNotIn("was not found", err.message)

    def test_invalid_timeout_reports_a_timeout_not_a_missing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "resume.docx")
            docx.write_bytes(b"fake docx")

            with patch(
                "resume.australian_rotate.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=30),
            ):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(docx), str(Path(td, "out.pdf"))))

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.ERROR)
        self.assertIn("timed out", err.message)
        self.assertNotIn("was not found", err.message)

    def test_rejects_missing_docx_before_invoking_the_converter(self) -> None:
        """Ordering is the point: the existence check gates the subprocess.

        Both the converter and ``subprocess.run`` are asserted un-called, so
        this fails loudly if the check is ever moved below the conversion.
        """
        with tempfile.TemporaryDirectory() as td:
            absent = Path(td, "ghost.docx")

            convert = MagicMock(return_value=_ok_result(Path(td, "out.pdf")))
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

            convert = MagicMock(return_value=_ok_result(Path(td, "out.pdf")))
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


class TestConverterRequiresAnOutputFile(unittest.TestCase):
    """A zero exit is not sufficient -- the PDF must actually be on disk.

    Formerly pinned as a defect by ``TestExportPdfSucceedsWithoutWritingFile``
    (PR #299).  ``convert_docx_to_pdf`` returned ``result.returncode == 0`` and
    never looked at the filesystem, so a LibreOffice run that exited 0 without
    writing anything -- an unreadable input, a full or read-only outdir -- was
    reported as success.  These tests assert the fixed behaviour: no output
    file means the conversion failed.
    """

    def test_invalid_zero_exit_without_an_output_file_reports_failure(self) -> None:
        result, _call = _capture_convert(
            "/in/a.docx", "/out/a.pdf", returncode=0, writes_output=False
        )

        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.NO_OUTPUT)

    def test_invalid_no_output_message_does_not_blame_a_missing_libreoffice(self) -> None:
        """The old message misdiagnosed this case as "Is LibreOffice installed?"."""
        result, _call = _capture_convert(
            "/in/a.docx", "/out/a.pdf", returncode=0, writes_output=False
        )

        message = result.message
        self.assertIn("wrote no PDF", message)
        self.assertNotIn("not found", message)
        self.assertNotIn("was not found", message)
        # The missing-binary case keeps its own, different message.
        missing = ConversionResult(
            ok=False, failure=ConversionFailure.CONVERTER_MISSING
        ).message
        self.assertNotEqual(message, missing)
        self.assertIn("not found", missing)

    def test_invalid_no_output_surfaces_converter_stderr(self) -> None:
        """stderr was discarded before; it is what makes this case diagnosable."""
        result, _call = _capture_convert(
            "/in/a.docx",
            "/out/a.pdf",
            returncode=0,
            stderr="Error: source file could not be loaded",
            writes_output=False,
        )

        self.assertIn("source file could not be loaded", result.detail())

    def test_detail_without_stderr_is_just_the_message(self) -> None:
        result = ConversionResult(ok=False, failure=ConversionFailure.NO_OUTPUT)

        self.assertEqual(result.detail(), result.message)
        self.assertNotIn("LibreOffice reported", result.detail())

    def test_invalid_success_requires_the_docx_stem_name_not_the_requested_name(
        self,
    ) -> None:
        """The file checked is ``<docx_stem>.pdf`` in the outdir.

        Checking the *requested* path instead would still report failure here,
        but would wrongly report failure on the normal rename path where the
        two names differ -- so pin which name is consulted.
        """
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "source.docx")
            docx.write_bytes(b"fake docx")
            # LibreOffice writes source.pdf; the caller asked for final.pdf.
            Path(td, "source.pdf").write_bytes(b"%PDF-1.4")
            requested = Path(td, "final.pdf")

            runner = _fake_run(0)
            with patch("resume.australian_rotate.subprocess.run", runner):
                result = convert_docx_to_pdf(str(docx), str(requested))

            self.assertTrue(result)
            self.assertEqual(result.pdf_path, Path(td, "source.pdf"))


class TestExportPdfFailsLoudlyWhenNoPdfIsWritten(unittest.TestCase):
    """``export-pdf`` must never exit 0 without a PDF at the reported path.

    This is the user-visible half of the fix.  Previously the command found
    ``actual.exists()`` false, skipped the rename silently, printed the
    requested path and returned 0 -- handing the caller a path to a file that
    was not there, so a downstream step failed later and further from the
    cause.
    """

    @staticmethod
    def _run_with_silent_success(td: str) -> tuple[CLIError, Path, str]:
        """Drive ``cmd_export_pdf`` with a converter that writes nothing."""
        docx = Path(td, "resume.docx")
        docx.write_bytes(b"fake docx")
        requested = Path(td, "final.pdf")

        # A real subprocess-level silent success: exit 0, no file produced.
        runner = _fake_run(0, stderr="Error: source file could not be loaded")
        buf = io.StringIO()
        with patch("resume.australian_rotate.subprocess.run", runner):
            with redirect_stdout(buf):
                try:
                    cmd_export_pdf(_export_args(str(docx), str(requested)))
                except CLIError as exc:
                    return exc, requested, buf.getvalue()
        raise AssertionError("cmd_export_pdf returned instead of raising CLIError")

    def test_invalid_zero_exit_without_a_pdf_raises_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            err, _requested, _out = self._run_with_silent_success(td)

            self.assertEqual(err.code, ExitCode.ERROR)

    def test_invalid_zero_exit_without_a_pdf_prints_no_path(self) -> None:
        """Nothing may reach stdout: a printed path is what misled the caller."""
        with tempfile.TemporaryDirectory() as td:
            _err, requested, out = self._run_with_silent_success(td)

            self.assertEqual(out.strip(), "")
            self.assertFalse(requested.exists())

    def test_invalid_message_does_not_claim_libreoffice_is_missing(self) -> None:
        """LibreOffice ran -- saying it is not installed misdiagnoses the fault."""
        with tempfile.TemporaryDirectory() as td:
            err, _requested, _out = self._run_with_silent_success(td)

            self.assertIn("wrote no PDF", err.message)
            self.assertNotIn("Is LibreOffice installed?", err.message)
            self.assertNotIn("was not found", err.message)

    def test_invalid_message_includes_the_converter_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            err, _requested, _out = self._run_with_silent_success(td)

            self.assertIn("source file could not be loaded", err.message)

    def test_invalid_hint_points_at_the_output_directory_not_an_install(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            err, _requested, _out = self._run_with_silent_success(td)

            self.assertIsNotNone(err.hint)
            assert err.hint is not None  # nosec B101 - type narrowing for mypy
            self.assertIn("writable", err.hint)
            self.assertNotIn("brew install", err.hint)

    def test_invalid_missing_binary_still_reports_an_install_hint(self) -> None:
        """The other mode keeps the install guidance -- the two stay distinct."""
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td, "resume.docx")
            docx.write_bytes(b"fake docx")

            with patch(
                "resume.australian_rotate.subprocess.run",
                side_effect=FileNotFoundError(2, "No such file or directory", "soffice"),
            ):
                with self.assertRaises(CLIError) as ctx:
                    cmd_export_pdf(_export_args(str(docx), str(Path(td, "out.pdf"))))

        err = ctx.exception
        self.assertEqual(err.code, ExitCode.ERROR)
        self.assertIn("LibreOffice", err.message)
        self.assertIn("not found", err.message)
        assert err.hint is not None  # nosec B101 - type narrowing for mypy
        self.assertIn("soffice", err.hint)
        self.assertIn("install", err.hint.lower())


class TestConversionNeverShellsOut(unittest.TestCase):
    """Guard: this module must not depend on a real LibreOffice install."""

    def test_no_real_soffice_is_invoked_when_subprocess_is_patched(self) -> None:
        """A patched runner intercepts the call, so PATH is never consulted."""
        runner = _fake_run(0)
        with patch("resume.australian_rotate.subprocess.run", runner):
            with patch.object(Path, "is_file", lambda _self: True):
                result = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertTrue(result)
        runner.assert_called_once()
        self.assertEqual(runner.call_args[0][0][0], "soffice")

    def test_invalid_scrubbed_path_still_yields_false_not_an_exception(self) -> None:
        """Even with no PATH at all the converter degrades to False.

        ``subprocess.run`` is still patched, so nothing is executed; this pins
        that the no-binary outcome is a clean falsy result.
        """
        with patch.dict(os.environ, {"PATH": ""}, clear=False):
            with patch(
                "resume.australian_rotate.subprocess.run",
                side_effect=FileNotFoundError(2, "No such file or directory", "soffice"),
            ):
                result = convert_docx_to_pdf("/in/a.docx", "/out/a.pdf")

        self.assertFalse(result)
        self.assertIs(result.failure, ConversionFailure.CONVERTER_MISSING)


if __name__ == "__main__":
    unittest.main()
