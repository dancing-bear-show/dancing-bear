from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import os
import json
import time

from ..cache import MailCache


class CacheMixin:
    """Lightweight config/message cache helpers shared by providers.

    Uses `MailCache` for message metadata/full. Adds a simple JSON cache for
    provider config endpoints with TTL under `{cache_dir}/{provider}/config/*`.
    """

    def __init__(self, cache_dir: Optional[str]) -> None:
        self.cache_dir = cache_dir
        self.cache = MailCache(cache_dir) if cache_dir else None

    # ---- Config JSON cache ----
    def _cfg_cache_path(self, provider: str, name: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, provider, "config", f"{name}.json")

    def cfg_get_json(self, provider: str, name: str, ttl: int) -> Optional[Any]:
        p = self._cfg_cache_path(provider, name)
        if not p or not os.path.exists(p):
            return None
        try:
            if ttl > 0:
                age = time.time() - os.path.getmtime(p)
                if age > ttl:
                    return None
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def cfg_put_json(self, provider: str, name: str, data: Any) -> None:
        p = self._cfg_cache_path(provider, name)
        if not p:
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except Exception:
            pass


class BaseProvider(ABC, CacheMixin):
    """Abstract email provider interface used by CLI orchestration.

    Providers should implement the minimal surface needed by current commands.
    """

    def __init__(self, *, credentials_path: str, token_path: str, cache_dir: Optional[str] = None) -> None:
        CacheMixin.__init__(self, cache_dir)
        self.credentials_path = credentials_path
        self.token_path = token_path

    # ---- lifecycle / info ----
    @abstractmethod
    def authenticate(self) -> None:
        ...

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        ...

    # ---- labels ----
    @abstractmethod
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_label_id_map(self) -> Dict[str, str]:
        ...

    @abstractmethod
    def create_label(self, **body: Any) -> Dict[str, Any]:
        ...

    @abstractmethod
    def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def ensure_label(self, name: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    def delete_label(self, label_id: str) -> None:
        ...

    # ---- filters ----
    @abstractmethod
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def delete_filter(self, filter_id: str) -> None:
        ...

    # ---- forwarding ----
    @abstractmethod
    def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_verified_forwarding_addresses(self) -> List[str]:
        ...

    # ---- sweeping / messages ----
    @abstractmethod
    def list_message_ids(
        self,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> List[str]:
        ...

    @abstractmethod
    def batch_modify_messages(
        self,
        ids: List[str],
        add_label_ids: Optional[List[str]] = None,
        remove_label_ids: Optional[List[str]] = None,
    ) -> None:
        ...

    # ---- signatures ----
    @abstractmethod
    def list_signatures(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def update_signature(self, send_as_email: str, signature_html: str) -> Dict[str, Any]:
        ...

    # ---- capabilities ----
    def capabilities(self) -> set[str]:
        """Return a set of capability strings supported by the provider.

        Example keys: 'labels', 'filters', 'sweep', 'forwarding', 'signatures'.
        Default is an empty set; concrete providers should override.
        """
        return set()
