"""Attachment listing and download commands for messages.

Split out of commands.py to keep that module focused on search/summarize.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from .commands import _MSG_ID_REQUIRED


@dataclass(frozen=True)
class AttachmentInfo:
    """Metadata for a single message attachment."""
    filename: str
    mime_type: str
    attachment_id: str
    size: int


def list_message_attachments(message: dict) -> list[AttachmentInfo]:
    """Return attachment metadata from a full Gmail message dict.

    Recursively walks payload.parts and returns one AttachmentInfo per
    part that has a non-empty filename and a body.attachmentId.
    """
    payload = message.get("payload") or {}
    return _collect_attachment_parts(payload)


def _collect_attachment_parts(part: dict) -> list[AttachmentInfo]:
    """Recursively collect attachment parts from a message part."""
    results: list[AttachmentInfo] = []
    filename = (part.get("filename") or "").strip()
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId") or ""
    if filename and attachment_id:
        results.append(AttachmentInfo(
            filename=filename,
            mime_type=part.get("mimeType") or "",
            attachment_id=attachment_id,
            size=int(body.get("size") or 0),
        ))
    for sub in (part.get("parts") or []):
        results.extend(_collect_attachment_parts(sub))
    return results


_FALLBACK_ATTACHMENT_NAME = "attachment"


def _sanitize_filename(filename: str) -> str:
    """Return a safe basename, stripping path separators to prevent path traversal.

    Degenerate results ("", ".", "..") resolve to a directory rather than a file,
    so they fall back to a fixed placeholder name.
    """
    import os
    base = os.path.basename(filename.replace("\\", "/")).strip()
    if base in ("", ".", ".."):
        return _FALLBACK_ATTACHMENT_NAME
    return base


def run_messages_list_attachments(args) -> int:
    """List attachments in a Gmail message."""
    import json
    import sys
    from ..utils.cli_helpers import gmail_provider_from_args

    msg_id = getattr(args, "id", None)
    if not msg_id:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    client = gmail_provider_from_args(args)
    client.authenticate()
    try:
        msg = client.get_message(msg_id, fmt="full")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1
    attachments = list_message_attachments(msg)

    if not attachments:
        print("No attachments found.")
        return 0

    if getattr(args, "json", False):
        rows = [
            {
                "filename": a.filename,
                "mimeType": a.mime_type,
                "attachmentId": a.attachment_id,
                "size": a.size,
            }
            for a in attachments
        ]
        print(json.dumps(rows, indent=2))
    else:
        for a in attachments:
            print(f"{a.filename}  ({a.mime_type}, {a.size} bytes)  id={a.attachment_id}")
    return 0


def _print_attachment_choices(attachments: list[AttachmentInfo]) -> None:
    """Print attachment filename/id pairs to stderr as disambiguation help."""
    import sys
    for a in attachments:
        print(f"  {a.filename}  id={a.attachment_id}", file=sys.stderr)


def _resolve_by_filename(
    attachments: list[AttachmentInfo], filename_filter: str
) -> tuple[AttachmentInfo | None, int]:
    """Select the single attachment matching a filename."""
    import sys

    matched = [a for a in attachments if a.filename == filename_filter]
    if not matched:
        print(f"No attachment with filename '{filename_filter}' found.", file=sys.stderr)
        print("Available attachments:", file=sys.stderr)
        _print_attachment_choices(attachments)
        return None, 1
    if len(matched) > 1:
        print(
            f"Multiple attachments named '{filename_filter}'; "
            "specify --attachment-id instead:",
            file=sys.stderr,
        )
        _print_attachment_choices(matched)
        return None, 1
    return matched[0], 0


def _resolve_by_attachment_id(
    attachments: list[AttachmentInfo], attachment_id: str
) -> tuple[AttachmentInfo | None, int]:
    """Select the attachment with a given attachment id."""
    import sys

    matched = [a for a in attachments if a.attachment_id == attachment_id]
    if not matched:
        print(f"No attachment with id '{attachment_id}' found.", file=sys.stderr)
        return None, 1
    return matched[0], 0


def _resolve_attachment(
    attachments: list[AttachmentInfo],
    attachment_id: str | None,
    filename_filter: str | None,
) -> tuple[AttachmentInfo | None, int]:
    """Select one attachment from a list.

    Returns (chosen, 0) on success or (None, 1) on failure (error already printed).
    """
    import sys

    if filename_filter and attachment_id:
        print(
            "Specify only one of --attachment-id or --filename, not both.",
            file=sys.stderr,
        )
        return None, 1
    if filename_filter:
        return _resolve_by_filename(attachments, filename_filter)
    if attachment_id:
        return _resolve_by_attachment_id(attachments, attachment_id)
    if len(attachments) == 1:
        return attachments[0], 0
    print("Multiple attachments found; specify --attachment-id or --filename:", file=sys.stderr)
    _print_attachment_choices(attachments)
    return None, 1


def _resolve_output_path(chosen: AttachmentInfo, out_arg: str | None, out_dir_arg: str) -> Path:
    """Determine the output file path for a downloaded attachment."""
    safe_name = _sanitize_filename(chosen.filename)
    if out_arg:
        out_path = Path(out_arg)
        if out_path.is_dir():
            return out_path / safe_name
        return out_path
    return Path(out_dir_arg) / safe_name


def run_messages_download_attachment(args) -> int:
    """Download an attachment from a Gmail message to disk."""
    import sys
    from ..utils.cli_helpers import gmail_provider_from_args

    msg_id = getattr(args, "id", None)
    if not msg_id:
        print(_MSG_ID_REQUIRED, file=sys.stderr)
        return 1

    client = gmail_provider_from_args(args)
    client.authenticate()
    try:
        msg = client.get_message(msg_id, fmt="full")
    except Exception as exc:
        print(f"Failed to fetch message '{msg_id}': {exc}", file=sys.stderr)
        return 1
    attachments = list_message_attachments(msg)

    if not attachments:
        print("No attachments found in this message.", file=sys.stderr)
        return 1

    chosen, rc = _resolve_attachment(
        attachments,
        attachment_id=getattr(args, "attachment_id", None),
        filename_filter=getattr(args, "filename", None),
    )
    if chosen is None:
        return rc

    out_path = _resolve_output_path(
        chosen,
        out_arg=getattr(args, "out", None),
        out_dir_arg=getattr(args, "out_dir", None) or ".",
    )

    try:
        data = client.get_attachment(msg_id, chosen.attachment_id)
    except Exception as exc:
        print(f"Failed to fetch attachment '{chosen.filename}': {exc}", file=sys.stderr)
        return 1

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    except OSError as exc:
        print(f"Failed to write {out_path}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {out_path} ({len(data)} bytes)")
    return 0
