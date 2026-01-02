"""Processors for signatures pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    SignaturesExportPayload,
    SignaturesSyncPayload,
    SignaturesNormalizePayload,
)


class _SafeDict(dict):
    """Dict that returns placeholder for missing keys."""

    def __missing__(self, k):
        return "{" + k + "}"


def _inline_css(html: str) -> str:
    """Inline CSS using premailer if available."""
    try:
        from premailer import transform  # type: ignore

        return transform(html)
    except Exception:
        return html


def _render_template(template_html: str, subs: Dict[str, str]) -> str:
    """Render template with safe substitution."""
    try:
        return template_html.format_map(_SafeDict(**subs))
    except Exception:
        return template_html


@dataclass
class SignaturesExportResult:
    """Result of signatures export."""

    gmail_signatures: List[Dict[str, Any]] = field(default_factory=list)
    default_html: Optional[str] = None
    out_path: Path = None  # type: ignore
    ios_asset_path: Optional[Path] = None


@dataclass
class SignaturesSyncResult:
    """Result of signatures sync."""

    gmail_updates: List[str] = field(default_factory=list)
    ios_asset_written: Optional[Path] = None
    outlook_note_written: Optional[Path] = None
    dry_run: bool = False


@dataclass
class SignaturesNormalizeResult:
    """Result of signatures normalize."""

    out_path: Path = None  # type: ignore
    success: bool = True


class SignaturesExportProcessor(Processor[SignaturesExportPayload, ResultEnvelope[SignaturesExportResult]]):
    """Export signatures from Gmail."""

    def process(self, payload: SignaturesExportPayload) -> ResultEnvelope[SignaturesExportResult]:
        try:
            result = SignaturesExportResult(out_path=payload.out_path)
            payload.assets_dir.mkdir(parents=True, exist_ok=True)

            # Get Gmail client if credentials available
            try:
                client = payload.context.get_gmail_client()
                client.authenticate()
                for sa in client.list_signatures():
                    result.gmail_signatures.append(
                        {
                            "sendAs": sa.get("sendAsEmail"),
                            "isPrimary": sa.get("isPrimary", False),
                            "signature_html": sa.get("signature", ""),
                            "displayName": sa.get("displayName"),
                        }
                    )
                # Set default from primary
                prim = next((s for s in result.gmail_signatures if s.get("isPrimary")), None)
                if prim and prim.get("signature_html"):
                    result.default_html = prim["signature_html"]
                    ios_path = payload.assets_dir / "ios_signature.html"
                    ios_path.write_text(prim["signature_html"], encoding="utf-8")
                    result.ios_asset_path = ios_path
            except Exception:  # nosec B110 - no Gmail credentials
                pass

            return ResultEnvelope(status="success", payload=result)
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class SignaturesSyncProcessor(Processor[SignaturesSyncPayload, ResultEnvelope[SignaturesSyncResult]]):
    """Sync signatures to Gmail and write assets."""

    def process(self, payload: SignaturesSyncPayload) -> ResultEnvelope[SignaturesSyncResult]:
        try:
            result = SignaturesSyncResult(dry_run=payload.dry_run)
            sigs = payload.config.get("signatures") or {}
            default_html = sigs.get("default_html")

            # Gmail sync
            try:
                client = payload.context.get_gmail_client()
                client.authenticate()
                current = {s.get("sendAsEmail"): s for s in client.list_signatures()}
                desired = sigs.get("gmail") or []

                if not desired and default_html:
                    # Apply default to primary send-as
                    for sa in current.values():
                        if not sa.get("isPrimary"):
                            continue
                        email = sa.get("sendAsEmail")
                        disp = sa.get("displayName") or payload.account_display_name
                        html_final = _inline_css(
                            _render_template(default_html, {"displayName": disp or "", "email": email or ""})
                        )
                        if payload.dry_run:
                            result.gmail_updates.append(f"Would update {email} (primary)")
                        else:
                            client.update_signature(email, html_final)
                            result.gmail_updates.append(f"Updated {email}")
                else:
                    for ent in desired:
                        email = ent.get("sendAs")
                        html = ent.get("signature_html") or default_html
                        if not email or not html:
                            continue
                        if payload.send_as and email != payload.send_as:
                            continue
                        disp = (current.get(email) or {}).get("displayName") or payload.account_display_name
                        html_final = _inline_css(_render_template(html, {"displayName": disp or "", "email": email}))
                        if payload.dry_run:
                            result.gmail_updates.append(f"Would update {email}")
                        else:
                            client.update_signature(email, html_final)
                            result.gmail_updates.append(f"Updated {email}")
            except Exception:  # nosec B110 - no Gmail credentials
                pass

            # iOS asset
            ios = sigs.get("ios")
            if default_html and ios is not None:
                out = Path("signatures_assets/ios_signature.html")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(default_html, encoding="utf-8")
                result.ios_asset_written = out

            # Outlook note
            if sigs.get("outlook") or default_html:
                note = Path("signatures_assets/OUTLOOK_README.txt")
                note.parent.mkdir(parents=True, exist_ok=True)
                note.write_text(
                    "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                    "Use the exported HTML (ios_signature.html) and paste into Outlook signature settings,\n"
                    "or configure roaming signatures as per Microsoft guidance.",
                    encoding="utf-8",
                )
                result.outlook_note_written = note

            return ResultEnvelope(status="success", payload=result)
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class SignaturesNormalizeProcessor(Processor[SignaturesNormalizePayload, ResultEnvelope[SignaturesNormalizeResult]]):
    """Normalize signature HTML with variable substitution."""

    def process(self, payload: SignaturesNormalizePayload) -> ResultEnvelope[SignaturesNormalizeResult]:
        try:
            sigs = payload.config.get("signatures") or {}
            html = sigs.get("default_html")
            if not html:
                g = sigs.get("gmail") or []
                if g and isinstance(g, list):
                    html = g[0].get("signature_html")
            if not html:
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "No signature HTML found in config", "code": 1},
                )

            html_rendered = _render_template(html, payload.variables)
            payload.out_html.parent.mkdir(parents=True, exist_ok=True)
            payload.out_html.write_text(_inline_css(html_rendered), encoding="utf-8")

            return ResultEnvelope(
                status="success",
                payload=SignaturesNormalizeResult(out_path=payload.out_html, success=True),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )
