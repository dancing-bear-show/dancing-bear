"""Consumers for signatures pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer

from ..context import MailContext
from ..yamlio import load_config


@dataclass
class SignaturesExportPayload:
    """Payload for signatures export."""

    context: MailContext
    out_path: Path
    assets_dir: Path


@dataclass
class SignaturesSyncPayload:
    """Payload for signatures sync."""

    context: MailContext
    config: Dict[str, Any]
    dry_run: bool = False
    send_as: Optional[str] = None
    account_display_name: Optional[str] = None


@dataclass
class SignaturesNormalizePayload:
    """Payload for signatures normalize."""

    config: Dict[str, Any]
    out_html: Path
    variables: Dict[str, str] = field(default_factory=dict)


class SignaturesExportConsumer(Consumer[SignaturesExportPayload]):
    """Consume args to create export payload."""

    def __init__(self, context: MailContext, out_path: Path, assets_dir: Path):
        self._context = context
        self._out_path = out_path
        self._assets_dir = assets_dir

    def consume(self) -> SignaturesExportPayload:
        return SignaturesExportPayload(
            context=self._context,
            out_path=self._out_path,
            assets_dir=self._assets_dir,
        )


class SignaturesSyncConsumer(Consumer[SignaturesSyncPayload]):
    """Consume args to create sync payload."""

    def __init__(
        self,
        context: MailContext,
        config_path: str,
        dry_run: bool = False,
        send_as: Optional[str] = None,
        account_display_name: Optional[str] = None,
    ):
        self._context = context
        self._config_path = config_path
        self._dry_run = dry_run
        self._send_as = send_as
        self._account_display_name = account_display_name

    def consume(self) -> SignaturesSyncPayload:
        config = load_config(self._config_path)
        return SignaturesSyncPayload(
            context=self._context,
            config=config,
            dry_run=self._dry_run,
            send_as=self._send_as,
            account_display_name=self._account_display_name,
        )


class SignaturesNormalizeConsumer(Consumer[SignaturesNormalizePayload]):
    """Consume args to create normalize payload."""

    def __init__(self, config_path: str, out_html: Path, variables: List[str]):
        self._config_path = config_path
        self._out_html = out_html
        self._variables = variables

    def consume(self) -> SignaturesNormalizePayload:
        config = load_config(self._config_path)
        vars_map = {}
        for pair in self._variables:
            if "=" in pair:
                k, v = pair.split("=", 1)
                vars_map[k] = v
        return SignaturesNormalizePayload(
            config=config,
            out_html=self._out_html,
            variables=vars_map,
        )
