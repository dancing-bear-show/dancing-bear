"""Australian (upside down) resume renderer.

Converts DOCX to PDF and rotates 180 degrees for Australian reading orientation.
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional


def convert_docx_to_pdf(docx_path: str, pdf_path: str) -> bool:
    """Convert DOCX to PDF using LibreOffice."""
    try:
        # Try LibreOffice command line conversion
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(Path(pdf_path).parent),
                docx_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


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
    output_pdf: Optional[str] = None,
    keep_temp: bool = False,
) -> Optional[str]:
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

    print(f"Converting {docx_path} to PDF...")
    if not convert_docx_to_pdf(docx_path, temp_pdf):
        print("Error: DOCX to PDF conversion failed. Is LibreOffice installed?", file=sys.stderr)
        print("Try: brew install --cask libreoffice (macOS)", file=sys.stderr)
        return None

    # LibreOffice outputs to same directory with .pdf extension
    actual_temp = str(docx_file.with_suffix(".pdf"))
    if Path(actual_temp).exists() and actual_temp != temp_pdf:
        Path(actual_temp).rename(temp_pdf)

    if not Path(temp_pdf).exists():
        print(f"Error: Expected PDF not created: {temp_pdf}", file=sys.stderr)
        return None

    print(f"Rotating PDF 180° for Australian orientation...")
    if not rotate_pdf_180(temp_pdf, output_pdf):
        print("Error: PDF rotation failed", file=sys.stderr)
        if not keep_temp:
            Path(temp_pdf).unlink(missing_ok=True)
        return None

    # Clean up temp file
    if not keep_temp:
        Path(temp_pdf).unlink(missing_ok=True)

    print(f"✓ Australian resume created: {output_pdf}")
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
