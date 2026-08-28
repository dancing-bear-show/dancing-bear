"""Consumers for auto pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.fileutil import load_json_or_exit
from core.pipeline import Consumer

from ..context import MailContext


@dataclass
class AutoProposePayload:
    """Payload for auto propose."""

    context: MailContext
    out_path: Path
    days: int
    pages: int
    protect: list[str] = field(default_factory=list)
    dry_run: bool = False
    log_path: str = "logs/auto_runs.jsonl"


@dataclass
class AutoSummaryPayload:
    """Payload for auto summary."""

    proposal: dict[str, Any]


@dataclass
class AutoApplyPayload:
    """Payload for auto apply."""

    context: MailContext
    proposal: dict[str, Any]
    cutoff_days: int | None = None
    batch_size: int = 500
    dry_run: bool = False
    log_path: str = "logs/auto_runs.jsonl"


class AutoProposeConsumer(Consumer[AutoProposePayload]):
    """Consume args to create propose payload."""

    def __init__(self, context: MailContext, **kwargs):
        self._context = context
        self._kwargs = kwargs

    def consume(self) -> AutoProposePayload:
        return AutoProposePayload(context=self._context, **self._kwargs)


class AutoSummaryConsumer(Consumer[AutoSummaryPayload]):
    """Consume proposal file to create summary payload."""

    def __init__(self, proposal_path: Path):
        self._proposal_path = proposal_path

    def consume(self) -> AutoSummaryPayload:
        proposal = load_json_or_exit(self._proposal_path)
        return AutoSummaryPayload(proposal=proposal)


class AutoApplyConsumer(Consumer[AutoApplyPayload]):
    """Consume args to create apply payload."""

    def __init__(self, context: MailContext, proposal_path: Path, **kwargs):
        self._context = context
        self._proposal_path = proposal_path
        self._kwargs = kwargs

    def consume(self) -> AutoApplyPayload:
        proposal = load_json_or_exit(self._proposal_path)
        return AutoApplyPayload(context=self._context, proposal=proposal, **self._kwargs)
