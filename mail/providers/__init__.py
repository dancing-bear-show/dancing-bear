from __future__ import annotations

from typing import Optional

from .base import BaseProvider


def get_provider(name: str, *, credentials_path: str, token_path: str, cache_dir: Optional[str] = None) -> BaseProvider:
    n = (name or "").lower()
    if n == "gmail":
        # Lazy import to avoid importing optional deps during --help
        from .gmail import GmailProvider  # type: ignore
        return GmailProvider(credentials_path=credentials_path, token_path=token_path, cache_dir=cache_dir)
    if n == "outlook":
        # For Outlook, `credentials_path` parameter is the client_id
        # Lazy import to avoid importing requests/msal during --help
        from .outlook import OutlookProvider  # type: ignore
        return OutlookProvider(client_id=credentials_path, token_path=token_path, cache_dir=cache_dir)
    raise ValueError(f"Unsupported provider: {name}")

__all__ = [
    "BaseProvider",
    "GmailProvider",
    "OutlookProvider",
    "get_provider",
]
