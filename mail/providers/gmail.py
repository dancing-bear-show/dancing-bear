from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseProvider
from ..gmail_api import GmailClient


class GmailProvider(BaseProvider):
    _provider_name = "gmail"

    def __init__(self, *, credentials_path: str, token_path: str, cache_dir: Optional[str] = None) -> None:
        super().__init__(credentials_path=credentials_path, token_path=token_path, cache_dir=cache_dir)
        self._client = GmailClient(credentials_path=credentials_path, token_path=token_path, cache_dir=cache_dir)

    # ---- lifecycle ----
    def authenticate(self) -> None:
        self._client.authenticate()

    def get_profile(self) -> Dict[str, Any]:
        return self._client.get_profile()

    # ---- labels ----
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        return self._client.list_labels(use_cache=use_cache, ttl=ttl)

    def get_label_id_map(self) -> Dict[str, str]:
        return self._client.get_label_id_map()

    def create_label(self, **body: Any) -> Dict[str, Any]:
        return self._client.create_label(**body)

    def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._client.update_label(label_id, body)

    def ensure_label(self, name: str, **kwargs: Any) -> str:
        return self._client.ensure_label(name, **kwargs)

    def delete_label(self, label_id: str) -> None:
        self._client.delete_label(label_id)

    # ---- filters ----
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        return self._client.list_filters(use_cache=use_cache, ttl=ttl)

    def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        return self._client.create_filter(criteria, action)

    def delete_filter(self, filter_id: str) -> None:
        self._client.delete_filter(filter_id)

    # ---- forwarding ----
    def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
        return self._client.list_forwarding_addresses_info()

    def get_verified_forwarding_addresses(self) -> List[str]:
        return self._client.get_verified_forwarding_addresses()

    def get_auto_forwarding(self) -> Dict[str, Any]:
        return self._client.get_auto_forwarding()

    def set_auto_forwarding(self, *, enabled: bool, email: Optional[str] = None, disposition: Optional[str] = None) -> Dict[str, Any]:
        return self._client.update_auto_forwarding(enabled=enabled, email=email, disposition=disposition)

    # ---- sweeping / messages ----
    def list_message_ids(
        self,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> List[str]:
        return self._client.list_message_ids(query=query, label_ids=label_ids, max_pages=max_pages, page_size=page_size)

    def batch_modify_messages(
        self,
        ids: List[str],
        add_label_ids: Optional[List[str]] = None,
        remove_label_ids: Optional[List[str]] = None,
    ) -> None:
        self._client.batch_modify_messages(ids, add_label_ids=add_label_ids, remove_label_ids=remove_label_ids)

    # ---- signatures ----
    def list_signatures(self) -> List[Dict[str, Any]]:
        return self._client.list_signatures()

    def update_signature(self, send_as_email: str, signature_html: str) -> Dict[str, Any]:
        return self._client.update_signature(send_as_email, signature_html)

    def capabilities(self) -> set[str]:
        return {"labels", "filters", "sweep", "forwarding", "signatures"}

    # --- message content ---
    def get_message_text(self, msg_id: str) -> str:
        return self._client.get_message_text(msg_id)

    def get_message(self, msg_id: str, fmt: str = "full") -> Dict[str, Any]:
        return self._client.get_message(msg_id, fmt=fmt)

    # --- messages metadata ---
    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[Dict[str, Any]]:
        return self._client.get_messages_metadata(ids, use_cache=use_cache)

    # --- sending / drafts ---
    def send_message_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict[str, Any]:
        return self._client.send_message_raw(raw_bytes, thread_id)

    def create_draft_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict[str, Any]:
        return self._client.create_draft_raw(raw_bytes, thread_id)
