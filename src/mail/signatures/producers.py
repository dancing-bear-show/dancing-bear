"""Producers for signatures pipelines."""
from __future__ import annotations

from typing import Any

from core.pipeline import BaseProducer

from core.yamlio import dump_config
from .processors import (
    SignaturesExportResult,
    SignaturesSyncResult,
    SignaturesNormalizeResult,
)


class SignaturesExportProducer(BaseProducer):
    """Produce signatures export output."""

    failure_message = "Signatures export failed."

    def _produce_success(self, payload: SignaturesExportResult, diagnostics: dict | None) -> None:
        doc: dict[str, Any] = {"signatures": {"gmail": payload.gmail_signatures, "ios": {}, "outlook": []}}
        if payload.default_html:
            doc["signatures"]["default_html"] = payload.default_html

        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(payload.out_path), doc)

        msg = f"Exported signatures to {payload.out_path}"
        if payload.ios_asset_path:
            msg += f"; iOS asset at {payload.ios_asset_path}"
        self._writer.print(msg)


class SignaturesSyncProducer(BaseProducer):
    """Produce signatures sync output."""

    failure_message = "Signatures sync failed."

    def _produce_success(self, payload: SignaturesSyncResult, diagnostics: dict | None) -> None:
        for update in payload.gmail_updates:
            self._writer.print(update)

        if payload.ios_asset_written:
            self._writer.print(f"Wrote iOS signature asset to {payload.ios_asset_written}")

        if payload.outlook_note_written:
            self._writer.print(f"Wrote Outlook guidance to {payload.outlook_note_written}")


class SignaturesNormalizeProducer(BaseProducer):
    """Produce signatures normalize output."""

    failure_message = "Signatures normalize failed."

    def _produce_success(self, payload: SignaturesNormalizeResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Wrote normalized signature to {payload.out_path}")
