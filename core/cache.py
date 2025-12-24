"""Shared caching utilities for providers and clients."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional


class ConfigCacheMixin:
    """Lightweight JSON cache for config/API responses with TTL support.

    Provides simple file-based caching under `{cache_dir}/{provider}/config/*.json`.
    Thread-safe for reads; writes are best-effort (failures silently ignored).

    Usage:
        class MyClient(ConfigCacheMixin):
            def __init__(self, cache_dir: Optional[str] = None):
                ConfigCacheMixin.__init__(self, cache_dir, provider="myprovider")

            def get_data(self, use_cache: bool = True, ttl: int = 300):
                if use_cache:
                    cached = self.cfg_get_json("data", ttl)
                    if cached is not None:
                        return cached
                result = self._fetch_from_api()
                if use_cache:
                    self.cfg_put_json("data", result)
                return result
    """

    _cfg_cache_dir: Optional[str]
    _cfg_provider: str

    def __init__(self, cache_dir: Optional[str], provider: str = "default") -> None:
        self._cfg_cache_dir = cache_dir
        self._cfg_provider = provider

    def _cfg_cache_path(self, name: str) -> Optional[str]:
        """Return path for a named cache file, or None if caching disabled."""
        if not self._cfg_cache_dir:
            return None
        return os.path.join(self._cfg_cache_dir, self._cfg_provider, "config", f"{name}.json")

    def cfg_get_json(self, name: str, ttl: int = 0) -> Optional[Any]:
        """Get cached JSON data if fresh, else None.

        Args:
            name: Cache key (becomes filename)
            ttl: Max age in seconds (0 = no expiry check)

        Returns:
            Cached data or None if missing/expired/invalid
        """
        path = self._cfg_cache_path(name)
        if not path or not os.path.exists(path):
            return None
        try:
            if ttl > 0:
                age = time.time() - os.path.getmtime(path)
                if age > ttl:
                    return None
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def cfg_put_json(self, name: str, data: Any) -> None:
        """Cache JSON data to file (best-effort, failures ignored).

        Args:
            name: Cache key (becomes filename)
            data: JSON-serializable data
        """
        path = self._cfg_cache_path(name)
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except Exception:
            pass  # nosec B110 - non-fatal cache write

    def cfg_clear(self) -> None:
        """Remove all cached config files for this provider."""
        path = self._cfg_cache_path(".")
        if not path:
            return
        import shutil
        config_dir = os.path.dirname(path)
        try:
            if os.path.isdir(config_dir):
                shutil.rmtree(config_dir)
        except Exception:
            pass  # nosec B110 - non-fatal cache clear
