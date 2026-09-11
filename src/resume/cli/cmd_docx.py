"""Docx-text and export-pdf command registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from core.cli_errors import CLIError, ExitCode
from core.cli_framework import CLIApp
from core.cli_framework_types import Argument

from .args import PROFILE_HELP_OUT, OUT_DIR_HELP
from .helpers import _resolve_out


def _read_docx_document(path: str) -> "tuple[str, list[str]] | None":
    """Return (document.xml text, archive member names), or None after reporting.

    Errors are printed to stderr and signalled as None so both docx-text modes
    share one set of failure messages.
    """
    import sys as _sys
    import zipfile

    try:
        zf = zipfile.ZipFile(path)
    except FileNotFoundError:
        print(f"docx-text: file not found: {path}", file=_sys.stderr)
        return None
    except zipfile.BadZipFile:
        print(f"docx-text: not a valid .docx (zip) file: {path}", file=_sys.stderr)
        return None
    with zf:
        names = list(zf.namelist())
        try:
            blob = zf.read("word/document.xml")
        except KeyError:
            print(f"docx-text: word/document.xml not found in {path}", file=_sys.stderr)
            return None

    # A DOCX body is UTF-8 by convention, not by guarantee -- the XML
    # declaration may name another encoding. Decoding strictly would reject a
    # readable document over one stray byte, so fall back to latin-1, which
    # cannot fail and leaves the ASCII markup this command greps for intact.
    try:
        return blob.decode("utf-8"), names
    except UnicodeDecodeError:
        print(
            f"docx-text: {path} is not valid UTF-8; decoded as latin-1 "
            "(non-ASCII characters may be wrong)",
            file=_sys.stderr,
        )
        return blob.decode("latin-1"), names


def _print_docx_structure(raw: str, names: list[str]) -> None:
    """Print counts of layout markup that commonly breaks resume extraction.

    Tables, text boxes and multi-column sections are the shapes a naive
    paragraph walk silently misreads, so an auditor needs the counts before
    trusting extracted text.
    """
    print("tables:", raw.count("<w:tbl>"))
    print("textboxes:", raw.count("<w:txbxContent>"))
    print("columns:", raw.count("<w:cols"))
    print("parts:", [n for n in names if "header" in n or "footer" in n])


def cmd_docx_text(args: argparse.Namespace) -> int:
    """Extract the visible text of a .docx file, or describe its layout markup.

    Strips XML tags and paragraph markers; unescapes HTML entities.
    Exits nonzero with a message on stderr if the file is missing or not a zip.
    """
    import html
    import re

    result = _read_docx_document(args.path)
    if result is None:
        return 1
    raw, names = result

    if args.structure:
        _print_docx_structure(raw, names)
        return 0

    raw = raw.replace("</w:p>", "\n")
    raw = re.sub(r"<[^>]+>", "", raw)
    print(html.unescape(raw))
    return 0


def cmd_export_pdf(args: argparse.Namespace) -> int:
    from resume.australian_rotate import convert_docx_to_pdf

    docx = Path(args.docx)
    if not docx.is_file():
        raise CLIError(f"{args.docx}: file not found", ExitCode.USAGE)

    out_pdf = _resolve_out(args, ".pdf", kind=docx.stem)
    # LibreOffice always writes <docx_stem>.pdf into the output directory;
    # when that path differs from out_pdf, rename it afterward.
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    conversion = convert_docx_to_pdf(str(docx), str(out_pdf))
    if not conversion:
        # The converter distinguishes a missing binary from a converter that
        # ran but produced nothing; surface that rather than always blaming a
        # missing LibreOffice install.
        raise CLIError(conversion.detail(), ExitCode.ERROR, hint=conversion.hint)

    # LibreOffice writes <docx_stem>.pdf into the outdir, not the exact target.
    # conversion.pdf_path is verified to exist, so the rename cannot silently
    # no-op into a reported path that holds no file.
    actual = conversion.pdf_path
    if actual is None:
        raise CLIError("conversion succeeded but pdf_path is None", ExitCode.ERROR)
    if actual != out_pdf:
        actual.rename(out_pdf)

    print(str(out_pdf))
    return 0


def register_docx_commands(app: CLIApp) -> None:
    """Register the docx-text and export-pdf commands on app."""
    _DOCX_TEXT_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("path",), {"help": "Path to the .docx file"}),
        (("--structure",), {"action": "store_true",
                            "help": "Report layout markup counts (tables/textboxes/columns) instead of text"}),
    ]
    for flags, kwargs in reversed(_DOCX_TEXT_ARGS):
        app._pending_arguments.append(Argument(flags, kwargs))
    app.command("docx-text", help="Dump visible text from a .docx file (for verification)")(cmd_docx_text)

    _EXPORT_PDF_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("--docx",), {"required": True, "help": "Input .docx file to convert"}),
        (("--out",), {"help": "Output PDF path (overrides --profile / --out-dir)"}),
        (("--profile",), {"help": PROFILE_HELP_OUT}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    for flags, kwargs in reversed(_EXPORT_PDF_ARGS):
        app._pending_arguments.append(Argument(flags, kwargs))
    app.command("export-pdf", help="Convert a .docx resume to PDF via LibreOffice")(cmd_export_pdf)
