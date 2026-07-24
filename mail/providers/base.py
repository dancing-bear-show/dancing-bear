from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.cache import ConfigCacheMixin
from ..cache import MailCache


class CacheMixin(ConfigCacheMixin):
    """Provider cache mixin combining ConfigCacheMixin with MailCache.

    Uses `MailCache` for message metadata/full. Inherits JSON config caching
    from `ConfigCacheMixin` for provider config endpoints.
    """

    def __init__(self, cache_dir: str | None, provider: str = "default") -> None:
        ConfigCacheMixin.__init__(self, cache_dir, provider)
        self.cache_dir = cache_dir
        self.cache = MailCache(cache_dir) if cache_dir else None


class BaseProvider(ABC, CacheMixin):
    """Abstract email provider interface used by CLI orchestration.

    Providers should implement the minimal surface needed by current commands.
    """

    # Subclasses should override this to set their provider name for caching
    _provider_name: str = "mail"

    def __init__(self, *, credentials_path: str, token_path: str, cache_dir: str | None = None) -> None:
        CacheMixin.__init__(self, cache_dir, self._provider_name)
        self.credentials_path = credentials_path
        self.token_path = token_path

    # ---- lifecycle / info ----
    @abstractmethod
    def authenticate(self) -> None:
        ...

    @abstractmethod
    def get_profile(self) -> dict[str, Any]:
        ...

    # ---- labels ----
    @abstractmethod
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_label_id_map(self) -> dict[str, str]:
        ...

    @abstractmethod
    def create_label(self, **body: Any) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_label(self, label_id: str, body: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def ensure_label(self, name: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    def delete_label(self, label_id: str) -> None:
        ...

    # ---- filters ----
    @abstractmethod
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def create_filter(self, criteria: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    def delete_filter(self, filter_id: str) -> None:
        ...

    # ---- forwarding ----
    @abstractmethod
    def list_forwarding_addresses_info(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_verified_forwarding_addresses(self) -> list[str]:
        ...

    # ---- sweeping / messages ----
    @abstractmethod
    def list_message_ids(
        self,
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> list[str]:
        ...

    @abstractmethod
    def batch_modify_messages(
        self,
        ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> None:
        ...

    # ---- signatures ----
    @abstractmethod
    def list_signatures(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def update_signature(self, send_as_email: str, signature_html: str) -> dict[str, Any]:
        ...

    # ---- capabilities ----
    def capabilities(self) -> set[str]:
        """Return a set of capability strings supported by the provider.

        Example keys: 'labels', 'filters', 'sweep', 'forwarding', 'signatures'.
        Default is an empty set; concrete providers should override.
        """
        return set()
