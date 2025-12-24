"""Consumers for auto pipelines."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer

from ..context import MailContext


@dataclass
class AutoProposePayload:
    """Payload for auto propose."""

    context: MailContext
    out_path: Path
    days: int
    pages: int
    protect: List[str] = field(default_factory=list)
    dry_run: bool = False
    log_path: str = "logs/auto_runs.jsonl"


@dataclass
class AutoSummaryPayload:
    """Payload for auto summary."""

    proposal: Dict[str, Any]


@dataclass
class AutoApplyPayload:
    """Payload for auto apply."""

    context: MailContext
    proposal: Dict[str, Any]
    cutoff_days: Optional[int] = None
    batch_size: int = 500
    dry_run: bool = False
    log_path: str = "logs/auto_runs.jsonl"


class AutoProposeConsumer(Consumer[AutoProposePayload]):
    """Consume args to create propose payload."""

    def __init__(
        self,
        context: MailContext,
        out_path: Path,
        days: int,
        pages: int,
        protect: List[str],
        dry_run: bool = False,
        log_path: str = "logs/auto_runs.jsonl",
    ):
        self._context = context
        self._out_path = out_path
        self._days = days
        self._pages = pages
        self._protect = protect
        self._dry_run = dry_run
        self._log_path = log_path

    def consume(self) -> AutoProposePayload:
        return AutoProposePayload(
            context=self._context,
            out_path=self._out_path,
            days=self._days,
            pages=self._pages,
            protect=self._protect,
            dry_run=self._dry_run,
            log_path=self._log_path,
        )


class AutoSummaryConsumer(Consumer[AutoSummaryPayload]):
    """Consume proposal file to create summary payload."""

    def __init__(self, proposal_path: Path):
        self._proposal_path = proposal_path

    def consume(self) -> AutoSummaryPayload:
        proposal = json.loads(self._proposal_path.read_text(encoding="utf-8"))
        return AutoSummaryPayload(proposal=proposal)


class AutoApplyConsumer(Consumer[AutoApplyPayload]):
    """Consume args to create apply payload."""

    def __init__(
        self,
        context: MailContext,
        proposal_path: Path,
        cutoff_days: Optional[int] = None,
        batch_size: int = 500,
        dry_run: bool = False,
        log_path: str = "logs/auto_runs.jsonl",
    ):
        self._context = context
        self._proposal_path = proposal_path
        self._cutoff_days = cutoff_days
        self._batch_size = batch_size
        self._dry_run = dry_run
        self._log_path = log_path

    def consume(self) -> AutoApplyPayload:
        proposal = json.loads(self._proposal_path.read_text(encoding="utf-8"))
        return AutoApplyPayload(
            context=self._context,
            proposal=proposal,
            cutoff_days=self._cutoff_days,
            batch_size=self._batch_size,
            dry_run=self._dry_run,
            log_path=self._log_path,
        )
