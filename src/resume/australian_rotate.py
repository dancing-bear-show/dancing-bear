"""Australian (upside down) resume renderer.

Converts DOCX to PDF and rotates 180 degrees for Australian reading orientation.
"""

from __future__ import annotations

import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core.cli_output import OutputWriter

_writer = OutputWriter()

CONVERT_TIMEOUT_SECONDS = 30


class ConversionFailure(Enum):
    """Why a DOCX to PDF conversion did not produce a usable PDF."""

    NONE = "none"
    CONVERTER_MISSING = "converter_missing"
    CONVERTER_TIMEOUT = "converter_timeout"
    CONVERTER_ERROR = "converter_error"
    NO_OUTPUT = "no_output"


@dataclass(frozen=True)
class ConversionResult:
    """Outcome of a single LibreOffice conversion attempt.

    ``bool(result)`` is the success test, so the two existing callers keep
    working unchanged while gaining access to *why* a conversion failed.
    """

    ok: bool
    failure: ConversionFailure = ConversionFailure.NONE
    stderr: str = ""
    pdf_path: Path | None = None

    def __bool__(self) -> bool:
        return self.ok

    @property
    def message(self) -> str:
        """One-line, user-facing explanation of the failure."""
        return _FAILURE_MESSAGES.get(self.failure, "DOCX to PDF conversion failed.")

    @property
    def hint(self) -> str | None:
        """Actionable next step, or None when there is nothing useful to suggest."""
        return _FAILURE_HINTS.get(self.failure)

    def detail(self) -> str:
        """The failure message with converter stderr appended when available."""
        stderr = self.stderr.strip()
        return f"{self.message} LibreOffice reported: {stderr}" if stderr else self.message


_FAILURE_MESSAGES: dict[ConversionFailure, str] = {
    ConversionFailure.CONVERTER_MISSING: (
        "DOCX to PDF conversion failed: LibreOffice ('soffice') was not found."
    ),
    ConversionFailure.CONVERTER_TIMEOUT: (
        f"DOCX to PDF conversion failed: LibreOffice timed out after "
        f"{CONVERT_TIMEOUT_SECONDS}s."
    ),
    ConversionFailure.CONVERTER_ERROR: (
        "DOCX to PDF conversion failed: LibreOffice exited with an error."
    ),
    ConversionFailure.NO_OUTPUT: (
        "DOCX to PDF conversion failed: LibreOffice exited successfully but "
        "wrote no PDF."
    ),
}

_FAILURE_HINTS: dict[ConversionFailure, str] = {
    ConversionFailure.CONVERTER_MISSING: (
        "install LibreOffice and ensure 'soffice' is on PATH "
        "(macOS: brew install --cask libreoffice)"
    ),
    ConversionFailure.CONVERTER_TIMEOUT: (
        "retry, or convert a smaller document; LibreOffice may be waiting on a "
        "stale profile lock"
    ),
    ConversionFailure.CONVERTER_ERROR: (
        "check that the .docx is readable and not corrupt"
    ),
    ConversionFailure.NO_OUTPUT: (
        "check that the output directory is writable and the .docx is not corrupt"
    ),
}


def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> ConversionResult:
    """Convert DOCX to PDF using LibreOffice.

    LibreOffice writes ``<docx_stem>.pdf`` into the parent directory of
    *pdf_path*, which is not necessarily *pdf_path* itself. Success requires
    both a zero exit status *and* that file existing on disk: LibreOffice can
    exit 0 having written nothing, and reporting that as success hands the
    caller a path to a file that is not there.

    Returns:
        A ConversionResult that is falsy on failure and carries the reason.
    """
    outdir = Path(pdf_path).parent
    try:
        # Try LibreOffice command line conversion
        result = subprocess.run(  # nosec B603 B607 - invoking known system PDF tool with trusted arguments
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                docx_path,
            ],
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ConversionResult(ok=False, failure=ConversionFailure.CONVERTER_TIMEOUT)
    except FileNotFoundError:
        return ConversionResult(ok=False, failure=ConversionFailure.CONVERTER_MISSING)

    stderr = result.stderr or ""
    if result.returncode != 0:
        return ConversionResult(
            ok=False, failure=ConversionFailure.CONVERTER_ERROR, stderr=stderr
        )

    produced = outdir / f"{Path(docx_path).stem}.pdf"
    if not produced.is_file():
        return ConversionResult(
            ok=False, failure=ConversionFailure.NO_OUTPUT, stderr=stderr
        )

    return ConversionResult(ok=True, stderr=stderr, pdf_path=produced)


def rotate_pdf_180(input_pdf: str, output_pdf: str) -> bool:
    """Rotate PDF 180 degrees using pypdf."""
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader, PdfWriter  # type: ignore
        except ImportError:
            print("Error: pypdf or PyPDF2 required. Install: pip install pypdf", file=sys.stderr)
            return False

    try:
        reader = PdfReader(input_pdf)
        writer = PdfWriter()

        for page in reader.pages:
            page.rotate(180)
            writer.add_page(page)

        with open(output_pdf, "wb") as f:
            writer.write(f)
        return True
    except Exception as e:  # nosec B110 - PDF rotation failure
        print(f"Error rotating PDF: {e}", file=sys.stderr)
        return False


def create_australian_resume(
    docx_path: str,
    output_pdf: str | None = None,
    keep_temp: bool = False,
) -> str | None:
    """Convert DOCX resume to upside-down PDF.

    Args:
        docx_path: Input DOCX file path
        output_pdf: Output PDF path (default: same name with .australian.pdf)
        keep_temp: Keep intermediate non-rotated PDF

    Returns:
        Path to output PDF if successful, None otherwise
    """
    docx_file = Path(docx_path)
    if not docx_file.exists():
        print(f"Error: {docx_path} not found", file=sys.stderr)
        return None

    # Determine output path
    if output_pdf is None:
        output_pdf = str(docx_file.with_suffix(".australian.pdf"))

    # Intermediate PDF (non-rotated)
    temp_pdf = str(docx_file.with_suffix(".temp.pdf"))

    _writer.print_data(f"Converting {docx_path} to PDF...")
    conversion = convert_docx_to_pdf(docx_path, temp_pdf)
    if not conversion:
        print(f"Error: {conversion.detail()}", file=sys.stderr)
        if conversion.hint:
            print(f"Try: {conversion.hint}", file=sys.stderr)
        return None

    # LibreOffice outputs to same directory with .pdf extension
    actual_temp = str(conversion.pdf_path)
    if actual_temp != temp_pdf:
        Path(actual_temp).rename(temp_pdf)

    _writer.print_data("Rotating PDF 180° for Australian orientation...")
    if not rotate_pdf_180(temp_pdf, output_pdf):
        print("Error: PDF rotation failed", file=sys.stderr)
        if not keep_temp:
            Path(temp_pdf).unlink(missing_ok=True)
        return None

    # Clean up temp file
    if not keep_temp:
        Path(temp_pdf).unlink(missing_ok=True)

    _writer.print_data(f"✓ Australian resume created: {output_pdf}")
    return output_pdf


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert resume DOCX to upside-down PDF (Australian orientation)"
    )
    parser.add_argument("docx", help="Input DOCX file")
    parser.add_argument(
        "-o", "--output",
        help="Output PDF path (default: <input>.australian.pdf)"
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep intermediate non-rotated PDF"
    )

    args = parser.parse_args()

    result = create_australian_resume(
        args.docx,
        output_pdf=args.output,
        keep_temp=args.keep_temp,
    )

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
