"""Mail assistant application context."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from core.context import AppContext


@dataclass
class MailContext(AppContext):
    gmail_client: Optional[Any] = field(default=None, init=False)

    @classmethod
    def from_args(cls, args: object, config: Optional[Dict[str, str]] = None) -> "MailContext":
        return cls(root=Path.cwd(), config=config or {}, args=args)

    def get_gmail_client(self):
        if self.gmail_client is not None:
            return self.gmail_client
        from .utils.cli_helpers import gmail_provider_from_args

        client = gmail_provider_from_args(self.args)
        client.authenticate()
        self.gmail_client = client
        return client
