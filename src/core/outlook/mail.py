"""Mail operations for Outlook via Microsoft Graph.

Includes messages and signatures. Labels/categories are in _mail_labels.py;
folders are in _mail_folders.py.
"""

from __future__ import annotations

from typing import Any, Protocol

from .client import OutlookClientBase, _requests
from .models import MessageSearchQuery, SearchParams
from ._mail_labels import LabelsFiltersMixin
from ._mail_folders import FoldersMixin
from core.constants import GRAPH_API_URL

_NEXT_LINK = "@odata.nextLink"

# Fields fetched by search_inbox_message_dicts so callers can build a full
# result row without a per-message get_message round trip.
_SEARCH_DICT_SELECT = (
    "id,subject,receivedDateTime,from,toRecipients,"
    "bodyPreview,hasAttachments,conversationId,isRead"
)


def _build_kql_search_url(params: MessageSearchQuery) -> str | None:
    """Build the KQL search URL from MessageSearchQuery, or None if no terms."""
    import urllib.parse
    sel = "$select=id,subject,receivedDateTime,from,bodyPreview,hasAttachments"
    folder_path = "mailFolders/inbox/messages" if params.only_inbox else "messages"
    kql_terms: list[str] = []
    if params.sender:
        kql_terms.append(f"from:{params.sender}")
    if params.query.strip():
        kql_terms.append(params.query.strip())
    if not kql_terms:
        return None
    encoded_query = urllib.parse.quote(f'"{" ".join(kql_terms)}"')
    return f"{GRAPH_API_URL}/me/{folder_path}?$search={encoded_query}&$top={int(params.top)}&{sel}"


def _days_cutoff_iso(days: Any) -> str:
    """Return the ISO-8601 Z cutoff for a days window, or "" when unbounded.

    Graph rejects ``$filter`` alongside ``$search``, so every search path applies
    its date window client-side against this cutoff.
    """
    if not days or int(days) <= 0:
        return ""
    import datetime as _dt
    start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=int(days))
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _within_cutoff(msg: dict[str, Any], cutoff: str) -> bool:
    """True when a message is inside the window.

    Messages missing ``receivedDateTime`` are kept rather than silently dropped:
    an absent field is unknown, not old.
    """
    if not cutoff:
        return True
    received = msg.get("receivedDateTime") or ""
    return not received or received >= cutoff


def _map_search_result(m: dict[str, Any]) -> dict[str, Any]:
    """Map a Graph API message to a search result dict."""
    addr = (m.get("from") or {}).get("emailAddress", {})
    return {
        "id": m.get("id"),
        "subject": m.get("subject", ""),
        "from": f"{addr.get('name', '')} <{addr.get('address', '')}>",
        "received": m.get("receivedDateTime") or "",
        "snippet": m.get("bodyPreview", ""),
        "has_attachments": m.get("hasAttachments", False),
    }


class _OutlookMailHost(Protocol):
    """Complete self-type for OutlookMailMixin methods that call cross-class attrs.

    Covers two distinct cases:
    - _fetch_search_ids/_fetch_search_dicts: need _headers_search from OutlookClientBase
    - search_inbox_message_dicts/search_inbox_messages: need _fetch_search_* siblings
      plus cache_dir/cfg_get_json/cfg_put_json from ConfigCacheMixin
    """

    # --- From OutlookClientBase ---
    def _headers_search(self) -> dict[str, str]: ...

    # --- From ConfigCacheMixin (via OutlookClientBase) ---
    cache_dir: str | None
    def cfg_get_json(self, name: str, ttl: int = ...) -> Any | None: ...
    def cfg_put_json(self, name: str, data: Any) -> None: ...

    # --- OutlookMailMixin's own sibling methods ---
    def _build_search_url(self, params: SearchParams) -> str: ...
    def _build_dict_search_url(self, params: SearchParams) -> str: ...
    def _fetch_search_ids(self, params: SearchParams) -> list[str]: ...
    def _fetch_search_dicts(self, params: SearchParams) -> list[dict[str, Any]]: ...


class OutlookMailMixin(LabelsFiltersMixin, FoldersMixin):
    """Mixin providing all mail operations (categories, rules, messages, folders).

    Requires OutlookClientBase methods: _headers, _headers_search, cfg_get_json, cfg_put_json, cfg_clear.
    """

    # -------------------- Messages --------------------
    def _build_search_url(self, params: "SearchParams") -> str:
        """Build the initial search URL from params.

        Encoding contract: ``params.search_query`` is a RAW, unquoted term.
        This method owns both the KQL quote-wrapping and the percent-encoding --
        callers must NOT pre-quote or pre-encode, or the term is double-wrapped.

        No ``$filter`` is emitted: Microsoft Graph rejects ``$search`` combined
        with ``$filter``. The ``params.days`` window is applied client-side in
        ``_fetch_search_ids`` instead, which is why ``$select`` includes
        ``receivedDateTime``.
        """
        import urllib.parse
        base = f"{GRAPH_API_URL}/me/mailFolders/inbox/messages"
        encoded_query = urllib.parse.quote(f'"{params.search_query}"')
        query_params = [
            f"$search={encoded_query}",
            f"$top={int(params.top)}",
            "$select=id,receivedDateTime",
        ]
        return base + "?" + "&".join(query_params)

    def _fetch_search_ids(self: "_OutlookMailHost", params: "SearchParams") -> list[str]:
        """Paginate through search results and collect message IDs.

        Applies the ``params.days`` window client-side, since Graph forbids
        pairing ``$filter`` with ``$search``. Messages missing
        ``receivedDateTime`` are kept rather than silently dropped.
        """
        cutoff = _days_cutoff_iso(params.days)
        ids: list[str] = []
        nxt: str | None = self._build_search_url(params)
        for _ in range(max(1, int(params.pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                mid = m.get("id")
                if mid and _within_cutoff(m, cutoff):
                    ids.append(mid)
            nxt = data.get(_NEXT_LINK)
            if not nxt:
                break
        return ids

    def _build_dict_search_url(self, params: "SearchParams") -> str:
        """Build the search URL for ``search_inbox_message_dicts``.

        Same contract as ``_build_search_url`` -- callers pass RAW, unquoted
        terms and this method owns the KQL quoting and percent-encoding -- but
        selects the full field set so results need no follow-up fetch.
        """
        import urllib.parse
        base = f"{GRAPH_API_URL}/me/mailFolders/inbox/messages"
        encoded_query = urllib.parse.quote(f'"{params.search_query}"')
        query_params = [
            f"$search={encoded_query}",
            f"$top={int(params.top)}",
            f"$select={_SEARCH_DICT_SELECT}",
        ]
        return base + "?" + "&".join(query_params)

    def _fetch_search_dicts(self: "_OutlookMailHost", params: "SearchParams") -> list[dict[str, Any]]:
        """Paginate through search results and collect full message dicts."""
        cutoff = _days_cutoff_iso(params.days)
        msgs: list[dict[str, Any]] = []
        nxt: str | None = self._build_dict_search_url(params)
        for _ in range(max(1, int(params.pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                if m.get("id") and _within_cutoff(m, cutoff):
                    msgs.append(m)
            nxt = data.get(_NEXT_LINK)
            if not nxt:
                break
        return msgs

    def search_inbox_message_dicts(
        self: "_OutlookMailHost",
        params: SearchParams,
    ) -> list[dict[str, Any]]:
        """Return full message dicts in Inbox matching the ``$search`` query.

        Unlike ``search_inbox_messages`` (which returns bare IDs and forces a
        per-message ``get_message`` round trip), this selects every field a
        result row needs in one request.

        ``params.search_query`` is a RAW, unquoted term -- see
        ``_build_dict_search_url``.
        """
        import hashlib

        key = None
        if self.cache_dir and params.use_cache:
            # Prefix must differ from search_inbox_messages' "search_": the two
            # cache different shapes (dicts vs IDs) for identical params, and a
            # shared prefix would let one return the other's payload.
            digest = hashlib.sha256(
                f"{params.search_query}|{params.top}|{params.pages}|{params.days}".encode()
            ).hexdigest()
            key = f"searchdicts_{digest}"
            cached = self.cfg_get_json(key, params.ttl)
            if isinstance(cached, list) and all(isinstance(x, dict) for x in cached):
                return cached
        msgs = self._fetch_search_dicts(params)
        if key and self.cache_dir and params.use_cache:
            try:
                self.cfg_put_json(key, msgs)
            except Exception:  # nosec B110 - non-fatal cache write
                pass
        return msgs

    def search_inbox_messages(
        self: "_OutlookMailHost",
        params: SearchParams,
    ) -> list[str]:
        """Return message IDs in Inbox matching $search query, optional days filter."""
        import hashlib

        key = None
        if self.cache_dir and params.use_cache:
            key = f"search_{hashlib.sha256(f'{params.search_query}|{params.top}|{params.pages}|{params.days}'.encode()).hexdigest()}"
            cached = self.cfg_get_json(key, params.ttl)
            if isinstance(cached, list):
                return [str(x) for x in cached]
        ids = self._fetch_search_ids(params)
        if key and self.cache_dir and params.use_cache:
            try:
                self.cfg_put_json(key, ids)
            except Exception:  # nosec B110 - non-fatal cache write
                pass
        return ids

    def list_messages(
        self: OutlookClientBase,
        folder: str = "inbox",
        top: int = 25,
        pages: int = 1,
    ) -> list[dict[str, Any]]:
        """List messages in a folder with pagination."""
        base = f"{GRAPH_API_URL}/me/mailFolders/{folder}/messages"
        url = f"{base}?$top={int(top)}&$orderby=receivedDateTime desc"
        msgs: list[dict[str, Any]] = []
        for _ in range(max(1, int(pages))):
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            msgs.extend(data.get("value", []))
            url = data.get(_NEXT_LINK)
            if not url:
                break
        return msgs

    def move_message(self: OutlookClientBase, msg_id: str, dest_folder_id: str) -> None:
        body = {"destinationId": dest_folder_id}
        r = _requests().post(
            f"{GRAPH_API_URL}/me/messages/{msg_id}/move",
            headers=self._headers(),
            json=body,
        )
        r.raise_for_status()

    def get_message(
        self: OutlookClientBase,
        msg_id: str,
        select_body: bool = True,
    ) -> dict[str, Any]:
        # Additive widening: existing callers read named keys, so extra fields
        # are inert for them while letting the provider-agnostic get/summarize
        # paths build a full record from one fetch.
        sel = (
            "$select=id,subject,receivedDateTime,sentDateTime,from,toRecipients,"
            "bodyPreview,isRead,conversationId"
        ) + (",body" if select_body else "")
        url = f"{GRAPH_API_URL}/me/messages/{msg_id}?{sel}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def search_messages(
        self: OutlookClientBase,
        query: str = "",
        params: MessageSearchQuery | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search mail messages matching query.

        Accepts either a MessageSearchQuery params object or keyword arguments
        (query, top, pages, after, sender, only_inbox).

        Args:
            query: KQL search string (e.g. 'Jing Zhang receipt')
            params: MessageSearchQuery with all search parameters.
            **kwargs: Legacy keyword arguments forwarded to MessageSearchQuery.
        """
        if params is None:
            params = MessageSearchQuery(query=query, **kwargs)
        nxt = _build_kql_search_url(params)
        if not nxt:
            return []
        msgs: list[dict[str, Any]] = []
        for _ in range(max(1, int(params.pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                if params.after and (m.get("receivedDateTime") or "")[:10] < params.after[:10]:
                    continue
                msgs.append(_map_search_result(m))
            nxt = data.get(_NEXT_LINK)
            if not nxt:
                break
        return msgs

    # -------------------- Signatures --------------------
    def list_signatures(self: OutlookClientBase) -> list[dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self: OutlookClientBase, signature_html: str) -> None:
        raise NotImplementedError("Outlook signatures cannot be updated programmatically via Graph v1.0")
