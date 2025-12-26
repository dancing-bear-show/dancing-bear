"""Base Outlook client with authentication and config caching."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from core.cache import ConfigCacheMixin
from core.constants import (
    GRAPH_API_URL,
    GRAPH_API_SCOPES,
    DEFAULT_REQUEST_TIMEOUT,
)

# Lazy optional deps: avoid importing on --help to prevent warnings/overhead
msal = None  # type: ignore
requests = None  # type: ignore

# Backwards-compat alias
DEFAULT_TIMEOUT = DEFAULT_REQUEST_TIMEOUT


def _msal():  # type: ignore
    global msal
    if msal is None:  # pragma: no cover - optional import
        import msal as _msal  # type: ignore
        msal = _msal
    return msal


class _TimeoutRequestsWrapper:
    """Wrapper around requests module that adds default timeout to all calls."""

    def __init__(self, requests_module, default_timeout):
        self._requests = requests_module
        self._timeout = default_timeout

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.post(url, **kwargs)

    def patch(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.patch(url, **kwargs)

    def delete(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.delete(url, **kwargs)

    def put(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.put(url, **kwargs)

    def head(self, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.head(url, **kwargs)


_requests_wrapper = None  # type: ignore


def _requests():  # type: ignore
    """Return requests module wrapped with default timeout."""
    global requests, _requests_wrapper
    if _requests_wrapper is None:  # pragma: no cover - optional import
        import requests as _req  # type: ignore
        requests = _req
        _requests_wrapper = _TimeoutRequestsWrapper(_req, DEFAULT_TIMEOUT)
    return _requests_wrapper


# Backwards-compat aliases for GRAPH and SCOPES
GRAPH = GRAPH_API_URL
SCOPES = GRAPH_API_SCOPES


class OutlookClientBase(ConfigCacheMixin):
    """Base Microsoft Graph client with authentication and config caching.

    Provides:
    - MSAL device flow authentication
    - Token refresh and caching
    - JSON config caching for API responses (via ConfigCacheMixin)
    """

    def __init__(
        self,
        client_id: str,
        tenant: str = "consumers",
        token_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        ConfigCacheMixin.__init__(self, cache_dir, provider="outlook")
        self.client_id = client_id
        self.tenant = tenant
        self.token_path = token_path
        self.cache_dir = cache_dir
        self._token: Optional[Dict[str, Any]] = None
        self._cache: Optional["msal.SerializableTokenCache"] = None
        self._app: Optional["msal.PublicClientApplication"] = None
        self._scopes: List[str] = ["https://graph.microsoft.com/.default"]
        self.GRAPH = GRAPH

    # -------------------- Auth --------------------
    def authenticate(self) -> None:
        cache = _msal().SerializableTokenCache()
        if self.token_path and os.path.exists(self.token_path):
            try:
                with open(self.token_path, "r", encoding="utf-8") as f:
                    data = f.read()
                try:
                    cache.deserialize(data)
                except Exception:
                    # Fallback: legacy simple token format
                    tok = json.loads(data)
                    if tok.get("access_token") and (tok.get("expires_at", 0) - 60) > time.time():
                        self._token = tok
                        self._cache = cache
                        self._app = _msal().PublicClientApplication(
                            self.client_id,
                            authority=f"https://login.microsoftonline.com/{self.tenant}"
                        )
                        return
            except Exception:  # noqa: S110 - token read failed, proceed with fresh auth
                pass

        app = _msal().PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant}",
            token_cache=cache,
        )
        # Try silent first
        acct = None
        try:
            accts = app.get_accounts()
            acct = accts[0] if accts else None
        except Exception:
            acct = None
        if acct is not None:
            result = app.acquire_token_silent(self._scopes, account=acct)
            if result and "access_token" in result:
                self._token = {
                    "access_token": result["access_token"],
                    "expires_at": time.time() + int(result.get("expires_in", 3600))
                }
                self._cache = cache
                self._app = app
                if self.token_path:
                    os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                    with open(self.token_path, "w", encoding="utf-8") as f:
                        f.write(cache.serialize())
                return

        # Start device flow if silent failed
        flow = app.initiate_device_flow(scopes=self._scopes)
        if "user_code" not in flow:
            raise RuntimeError("Failed to start device flow for Microsoft Graph")
        print(f"To sign in, visit {flow['verification_uri']} and enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Device flow failed: {result}")
        self._token = {
            "access_token": result["access_token"],
            "expires_at": time.time() + int(result.get("expires_in", 3600))
        }
        self._cache = cache
        self._app = app
        if self.token_path:
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("OutlookClient not authenticated")
        # Attempt silent refresh to keep sessions alive
        try:
            if self._app is not None:
                accts = self._app.get_accounts()
                acct = accts[0] if accts else None
                if acct is not None:
                    res = self._app.acquire_token_silent(self._scopes, account=acct)
                    if res and "access_token" in res:
                        self._token = {
                            "access_token": res["access_token"],
                            "expires_at": time.time() + int(res.get("expires_in", 3600))
                        }
                        if self._cache and self.token_path:
                            with open(self.token_path, "w", encoding="utf-8") as f:
                                f.write(self._cache.serialize())
        except Exception:  # noqa: S110 - silent token refresh failure
            pass
        return {
            "Authorization": f"Bearer {self._token['access_token']}",
            "Content-Type": "application/json"
        }

    def _headers_search(self) -> Dict[str, str]:
        h = self._headers()
        h["ConsistencyLevel"] = "eventual"
        return h

    # -------------------- Mailbox settings --------------------
    def get_mailbox_timezone(self) -> Optional[str]:
        try:
            r = _requests().get(f"{GRAPH}/me/mailboxSettings", headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            tz = (data.get("timeZone") or "").strip()
            return tz or None
        except Exception:
            return None
