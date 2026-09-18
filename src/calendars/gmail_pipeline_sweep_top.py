"""Gmail sweep-top-senders pipeline for calendar assistant."""
from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor
from core.text_utils import extract_email_address

from .gmail_service import QueryParams
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilderMixin,
    RequestConsumer,
)


# =============================================================================
# Gmail Sweep Top Senders Pipeline
# =============================================================================

@dataclass
class GmailSweepTopRequest:
    auth: GmailAuth
    query: str | None
    from_text: str | None
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    top: int
    out_path: Path | None


GmailSweepTopRequestConsumer = RequestConsumer[GmailSweepTopRequest]


@dataclass
class GmailSweepTopResult:
    top_senders: list[tuple[str, int]]
    freq_days: int
    inbox_only: bool
    out_path: Path | None


class GmailSweepTopProcessor(
    GmailServiceBuilderMixin, SafeProcessor[GmailSweepTopRequest, GmailSweepTopResult]
):
    def _process_safe(self, payload: GmailSweepTopRequest) -> GmailSweepTopResult:
        svc = self._service_builder(payload.auth)
        ids = svc.query_and_list_ids(
            QueryParams(
                explicit=payload.query,
                from_text=payload.from_text,
                days=payload.days,
                inbox_only=payload.inbox_only,
            ),
            max_pages=payload.pages,
            page_size=payload.page_size,
        )
        if not ids:
            return GmailSweepTopResult(top_senders=[], freq_days=payload.days, inbox_only=payload.inbox_only, out_path=payload.out_path)
        freq = self._count_senders(svc, ids)
        top = freq.most_common(max(1, payload.top))
        return GmailSweepTopResult(
            top_senders=top,
            freq_days=payload.days,
            inbox_only=payload.inbox_only,
            out_path=payload.out_path,
        )

    def _count_senders(self, svc, ids: list[str]) -> collections.Counter:
        """Count sender frequencies from message IDs."""
        freq: collections.Counter = collections.Counter()
        for mid in ids:
            sender = self._extract_sender(svc, mid)
            if sender:
                freq[sender] += 1
        return freq

    def _extract_sender(self, svc, mid: str) -> str | None:
        """Extract sender email address from a message."""
        try:
            msg = svc.get_message(mid)
        except Exception:  # nosec B112 - skip unreadable messages
            return None
        return self._parse_sender_from_message(msg)

    def _parse_sender_from_message(self, msg: dict[str, Any]) -> str | None:
        """Parse sender from Gmail message dict."""
        payload_data = msg.get("payload") or {}
        headers = payload_data.get("headers") or []
        for header in headers:
            if (header.get("name") or "").lower() == "from":
                return extract_email_address(header.get("value") or "")
        # Fallback: check top-level 'from' field
        if isinstance(msg, dict) and msg.get("from"):
            return extract_email_address(str(msg["from"]))
        return None


class GmailSweepTopProducer(BaseProducer):
    def _produce_success(self, payload: GmailSweepTopResult, diagnostics: dict[str, Any] | None) -> None:
        top = payload.top_senders
        if not top:
            self._writer.print("No sender stats available.")
            return
        self._writer.print(f"Top {len(top)} sender(s) in last {payload.freq_days}d (Inbox={payload.inbox_only}):")
        for sender, count in top:
            self._writer.print(f"- {sender}: {count}")
        if payload.out_path:
            from core.yamlio import dump_config

            filters = []
            for sender, _ in top:
                filters.append(
                    {
                        "name": f"Auto-archive {sender}",
                        "provider": "gmail",
                        "query": f"from:{sender}",
                        "actions": {
                            "archive": True,
                            "mark_read": True,
                            "labels": ["Sweep/Auto-Archive"],
                        },
                    }
                )
            dump_config(str(payload.out_path), {"filters": filters})
            self._writer.print(f"Wrote suggested Gmail filters to {payload.out_path}")
