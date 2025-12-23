from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseProvider
from ..outlook_api import OutlookClient


class OutlookProvider(BaseProvider):
    def __init__(self, *, client_id: str, tenant: str = "consumers", token_path: Optional[str] = None, cache_dir: Optional[str] = None) -> None:
        # Map BaseProvider ctor fields; credentials_path carries client_id conceptually
        super().__init__(credentials_path=client_id, token_path=token_path or "", cache_dir=cache_dir)
        self._client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token_path, cache_dir=cache_dir)

    # ---- lifecycle ----
    def authenticate(self) -> None:
        self._client.authenticate()

    def get_profile(self) -> Dict[str, Any]:
        # Graph profile not currently needed; return minimal structure
        return {"provider": "outlook"}

    # ---- labels (categories) ----
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        return self._client.list_labels(use_cache=use_cache, ttl=ttl)

    def get_label_id_map(self) -> Dict[str, str]:
        return self._client.get_label_id_map()

    def create_label(self, **body: Any) -> Dict[str, Any]:
        name = body.get("name") or body.get("displayName")
        color = body.get("color")
        return self._client.create_label(name=name, color=color)

    def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._client.update_label(label_id, body)

    def ensure_label(self, name: str, **kwargs: Any) -> str:
        return self._client.ensure_label(name, **kwargs)

    def delete_label(self, label_id: str) -> None:
        self._client.delete_label(label_id)

    # ---- filters (rules) ----
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        return self._client.list_filters(use_cache=use_cache, ttl=ttl)

    def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        return self._client.create_filter(criteria, action)

    def delete_filter(self, filter_id: str) -> None:
        self._client.delete_filter(filter_id)

    # ---- forwarding ----
    def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
        # Not supported via Graph v1.0 — return empty list
        return []

    def get_verified_forwarding_addresses(self) -> List[str]:
        return []

    # ---- sweeping / messages (not supported here) ----
    def list_message_ids(
        self,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> List[str]:
        raise NotImplementedError("OutlookProvider does not support message listing for sweeps")

    def batch_modify_messages(
        self,
        ids: List[str],
        add_label_ids: Optional[List[str]] = None,
        remove_label_ids: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError("OutlookProvider does not support batch message modify for sweeps")

    # ---- signatures ----
    def list_signatures(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self, send_as_email: str, signature_html: str) -> Dict[str, Any]:
        raise NotImplementedError("Outlook signatures cannot be updated via Graph v1.0")

    def capabilities(self) -> set[str]:
        return {"labels", "filters"}
