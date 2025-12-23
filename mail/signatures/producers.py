"""Producers for signatures pipelines."""
from __future__ import annotations

from typing import Any, Dict

from core.pipeline import Producer, ResultEnvelope

from ..yamlio import dump_config
from .processors import (
    SignaturesExportResult,
    SignaturesSyncResult,
    SignaturesNormalizeResult,
)


class SignaturesExportProducer(Producer[ResultEnvelope[SignaturesExportResult]]):
    """Produce signatures export output."""

    def produce(self, result: ResultEnvelope[SignaturesExportResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(diag.get("error", "Signatures export failed."))
            return

        payload = result.payload
        doc: Dict[str, Any] = {"signatures": {"gmail": payload.gmail_signatures, "ios": {}, "outlook": []}}
        if payload.default_html:
            doc["signatures"]["default_html"] = payload.default_html

        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(payload.out_path), doc)

        msg = f"Exported signatures to {payload.out_path}"
        if payload.ios_asset_path:
            msg += f"; iOS asset at {payload.ios_asset_path}"
        print(msg)


class SignaturesSyncProducer(Producer[ResultEnvelope[SignaturesSyncResult]]):
    """Produce signatures sync output."""

    def produce(self, result: ResultEnvelope[SignaturesSyncResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(diag.get("error", "Signatures sync failed."))
            return

        payload = result.payload
        for update in payload.gmail_updates:
            prefix = "" if not payload.dry_run else ""
            print(f"{prefix}{update}")

        if payload.ios_asset_written:
            print(f"Wrote iOS signature asset to {payload.ios_asset_written}")

        if payload.outlook_note_written:
            print(f"Wrote Outlook guidance to {payload.outlook_note_written}")


class SignaturesNormalizeProducer(Producer[ResultEnvelope[SignaturesNormalizeResult]]):
    """Produce signatures normalize output."""

    def produce(self, result: ResultEnvelope[SignaturesNormalizeResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(diag.get("error", "Signatures normalize failed."))
            return

        payload = result.payload
        print(f"Wrote normalized signature to {payload.out_path}")
