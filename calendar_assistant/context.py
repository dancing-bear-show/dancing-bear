from __future__ import annotations

"""Lightweight runtime context objects.

This module provides small OO wrappers used across command handlers to
centralize configuration resolution and client initialization without
changing CLI behavior.

Design goals:
- Keep optional dependencies lazily imported.
- Preserve existing environment/profile resolution semantics.
- Provide small, focused helpers that reduce duplication in __main__.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from personal_core.auth import resolve_outlook_credentials


@dataclass
class OutlookContext:
    """Encapsulates Outlook Graph configuration and client initialization.

    This class does not import heavy modules until a client is requested,
    keeping CLI parsing fast. Values may be provided directly or resolved
    from environment/profile when absent (matching existing behavior).
    """

    client_id: Optional[str] = None
    tenant: Optional[str] = None
    token_path: Optional[str] = None
    profile: Optional[str] = None

    def resolve(self) -> Tuple[Optional[str], str, Optional[str]]:
        """Resolve effective (client_id, tenant, token_path) via shared auth helper."""
        client_id, tenant, token_path = resolve_outlook_credentials(
            self.profile,
            self.client_id,
            self.tenant,
            self.token_path,
        )
        return client_id, tenant or "consumers", token_path

    def ensure_client(self):
        """Instantiate and authenticate an OutlookClient.

        Returns a ready client or raises if Outlook features are unavailable.
        """
        try:  # lazy heavy import
            from mail_assistant.outlook_api import OutlookClient  # type: ignore
        except Exception as e:  # pragma: no cover - optional dep
            raise RuntimeError(f"Outlook features unavailable: {e}") from e
        client_id, tenant, token_path = self.resolve()
        if not client_id:
            raise RuntimeError(
                "Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID or configure profile."
            )
        client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path)
        client.authenticate()
        return client
