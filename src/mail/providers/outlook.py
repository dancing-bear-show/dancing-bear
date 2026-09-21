from __future__ import annotations

from typing import Any

from .base import BaseProvider
from core.outlook import OutlookClient


class OutlookProvider(BaseProvider):
    _provider_name = "outlook"

    def __init__(self, *, client_id: str, tenant: str = "consumers", token_path: str | None = None, cache_dir: str | None = None) -> None:
        # Map BaseProvider ctor fields; credentials_path carries client_id conceptually
        super().__init__(credentials_path=client_id, token_path=token_path or "", cache_dir=cache_dir)
        self._client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=cache_dir)

    # ---- lifecycle ----
    def authenticate(self) -> None:
        self._client.authenticate()

    def get_profile(self) -> dict[str, Any]:
        # Graph profile not currently needed; return minimal structure
        return {"provider": "outlook"}

    # ---- labels (categories) ----
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> list[dict[str, Any]]:
        return self._client.list_labels(use_cache=use_cache, ttl=ttl)

    def get_label_id_map(self) -> dict[str, str]:
        return self._client.get_label_id_map()

    def create_label(self, **body: Any) -> dict[str, Any]:
        name = body.get("name") or body.get("displayName")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"create_label requires a non-empty string 'name' or 'displayName' in body; got {name!r}"
            )
        color = body.get("color")
        return self._client.create_label(name=name.strip(), color=color)

    def update_label(self, label_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.update_label(label_id, body)

    def ensure_label(self, name: str, **kwargs: Any) -> str:
        return self._client.ensure_label(name, **kwargs)

    def delete_label(self, label_id: str) -> None:
        self._client.delete_label(label_id)

    # ---- filters (rules) ----
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> list[dict[str, Any]]:
        return self._client.list_filters(use_cache=use_cache, ttl=ttl)

    def create_filter(self, criteria: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        return self._client.create_filter(criteria, action)

    def delete_filter(self, filter_id: str) -> None:
        self._client.delete_filter(filter_id)

    # ---- forwarding ----
    def list_forwarding_addresses_info(self) -> list[dict[str, Any]]:
        # Not supported via Graph v1.0 — return empty list
        return []

    def get_verified_forwarding_addresses(self) -> list[str]:
        return []

    # ---- sweeping / messages (not supported here) ----
    def list_message_ids(
        self,
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> list[str]:
        raise NotImplementedError("OutlookProvider does not support message listing for sweeps")

    def batch_modify_messages(
        self,
        ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> None:
        raise NotImplementedError("OutlookProvider does not support batch message modify for sweeps")

    # ---- signatures ----
    def list_signatures(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self, send_as_email: str, signature_html: str) -> dict[str, Any]:
        raise NotImplementedError("Outlook signatures cannot be updated via Graph v1.0")

    def capabilities(self) -> set[str]:
        return {"labels", "filters"}
