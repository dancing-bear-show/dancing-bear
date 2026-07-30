"""Protocol for Outlook service providers.

Defines the structural contract that any Outlook backend must satisfy so
callers can depend on the abstraction rather than the concrete client.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OutlookBaseProvider(Protocol):
    """Structural protocol for Outlook service providers.

    Any class that exposes a ``get_service()`` method returning a
    Microsoft Graph service object satisfies this protocol — no explicit
    inheritance required.

    Example::

        class MyOutlookProvider:
            def get_service(self) -> Any:
                return self._client  # an authenticated OutlookClient
    """

    def get_service(self) -> Any:
        """Return an authenticated Outlook service / client object."""
        ...
