from __future__ import annotations

"""Gmail calendar scan command implementations."""

import argparse
from pathlib import Path

from ..gmail_pipelines import (
    GmailAuth,
    GmailPlanProducer,
    GmailReceiptsProcessor,
    GmailReceiptsRequest,
    GmailReceiptsRequestConsumer,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailMailListProcessor,
    GmailMailListProducer,
    GmailMailListRequest,
    GmailMailListRequestConsumer,
    GmailSweepTopProcessor,
    GmailSweepTopProducer,
    GmailSweepTopRequest,
    GmailSweepTopRequestConsumer,
)


def run_gmail_mail_list(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailMailListRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 7)),
        pages=int(getattr(args, "pages", 1)),
        page_size=int(getattr(args, "page_size", 10)),
        inbox_only=bool(getattr(args, "inbox_only", False)),
    )
    envelope = GmailMailListProcessor().process(GmailMailListRequestConsumer(request).consume())
    GmailMailListProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_gmail_sweep_top(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailSweepTopRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 10)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        inbox_only=bool(getattr(args, "inbox_only", True)),
        top=int(getattr(args, "top", 10)),
        out_path=Path(getattr(args, "out")) if getattr(args, "out", None) else None,
    )
    envelope = GmailSweepTopProcessor().process(GmailSweepTopRequestConsumer(request).consume())
    GmailSweepTopProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_gmail_scan_classes(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailScanClassesRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 60)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        inbox_only=bool(getattr(args, "inbox_only", False)),
        calendar=getattr(args, "calendar", None),
        out_path=Path(getattr(args, "out")) if getattr(args, "out", None) else None,
    )
    envelope = GmailScanClassesProcessor().process(GmailScanClassesRequestConsumer(request).consume())
    GmailScanClassesProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_gmail_scan_receipts(args: argparse.Namespace) -> int:
    auth = GmailAuth(
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache_dir=getattr(args, "cache", None),
    )
    request = GmailReceiptsRequest(
        auth=auth,
        query=getattr(args, "query", None),
        from_text=getattr(args, "from_text", None),
        days=int(getattr(args, "days", 365)),
        pages=int(getattr(args, "pages", 5)),
        page_size=int(getattr(args, "page_size", 100)),
        calendar=getattr(args, "calendar", None),
        out_path=Path(getattr(args, "out")),
    )
    envelope = GmailReceiptsProcessor().process(GmailReceiptsRequestConsumer(request).consume())
    GmailPlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def run_gmail_scan_activerh(args: argparse.Namespace) -> int:
    """Generic targeting wrapper for ActiveRH receipts.

    Builds a broad query targeting Richmond Hill Active receipts and delegates to
    scan-receipts parser for class/range/time/location extraction.
    """
    from ..gmail_service import GmailService

    # If user supplied a query, just reuse scan-receipts logic directly
    if getattr(args, "query", None):
        return run_gmail_scan_receipts(args)
    # Construct via service helper and delegate
    q = GmailService.build_activerh_query(
        days=int(getattr(args, "days", 365)),
        explicit=None,
        programs=None,
        from_text=getattr(args, "from_text", None),
    )
    setattr(args, "query", q)
    return run_gmail_scan_receipts(args)
