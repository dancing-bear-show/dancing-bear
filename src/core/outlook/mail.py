"""Mail operations for Outlook via Microsoft Graph.

Includes messages and signatures. Labels/categories are in _mail_labels.py;
folders are in _mail_folders.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import OutlookClientBase, _requests
from .models import MessageSearchQuery, SearchParams
from ._mail_labels import LabelsFiltersMixin
from ._mail_folders import FoldersMixin
from core.constants import GRAPH_API_URL

_NEXT_LINK = "@odata.nextLink"


def _build_kql_search_url(params: MessageSearchQuery) -> Optional[str]:
    """Build the KQL search URL from MessageSearchQuery, or None if no terms."""
    import urllib.parse
    sel = "$select=id,subject,receivedDateTime,from,bodyPreview,hasAttachments"
    folder_path = "mailFolders/inbox/messages" if params.only_inbox else "messages"
    kql_terms: List[str] = []
    if params.sender:
        kql_terms.append(f"from:{params.sender}")
    if params.query.strip():
        kql_terms.append(params.query.strip())
    if not kql_terms:
        return None
    encoded_query = urllib.parse.quote(f'"{" ".join(kql_terms)}"')
    return f"{GRAPH_API_URL}/me/{folder_path}?$search={encoded_query}&$top={int(params.top)}&{sel}"


def _map_search_result(m: Dict[str, Any]) -> Dict[str, Any]:
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


class OutlookMailMixin(LabelsFiltersMixin, FoldersMixin):
    """Mixin providing all mail operations (categories, rules, messages, folders).

    Requires OutlookClientBase methods: _headers, _headers_search, cfg_get_json, cfg_put_json, cfg_clear.
    """

    # -------------------- Messages --------------------
    def _build_search_url(self, params: "SearchParams") -> str:
        """Build the initial search URL from params."""
        base = f"{GRAPH_API_URL}/me/mailFolders/inbox/messages"
        query_params = [f"$search=\"{params.search_query}\"", f"$top={int(params.top)}"]
        if params.days and int(params.days) > 0:
            import datetime as _dt
            start = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=int(params.days))
            start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            query_params.append(f"$filter=receivedDateTime ge {start_iso}")
        return base + "?" + "&".join(query_params)

    def _fetch_search_ids(self, params: "SearchParams") -> List[str]:
        """Paginate through search results and collect message IDs."""
        ids: List[str] = []
        nxt: Optional[str] = self._build_search_url(params)
        for _ in range(max(1, int(params.pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            ids.extend(m.get("id") for m in data.get("value", []) if m.get("id"))
            nxt = data.get(_NEXT_LINK)
            if not nxt:
                break
        return ids

    def search_inbox_messages(
        self: OutlookClientBase,
        params: SearchParams,
    ) -> List[str]:
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
    ) -> List[Dict[str, Any]]:
        """List messages in a folder with pagination."""
        base = f"{GRAPH_API_URL}/me/mailFolders/{folder}/messages"
        url = f"{base}?$top={int(top)}&$orderby=receivedDateTime desc"
        msgs: List[Dict[str, Any]] = []
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
    ) -> Dict[str, Any]:
        sel = "$select=subject,receivedDateTime,from,bodyPreview" + (",body" if select_body else "")
        url = f"{GRAPH_API_URL}/me/messages/{msg_id}?{sel}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def search_messages(
        self: OutlookClientBase,
        query: str = "",
        params: Optional[MessageSearchQuery] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
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
        msgs: List[Dict[str, Any]] = []
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

    def get_attachments(
        self: OutlookClientBase,
        msg_id: str,
    ) -> List[Dict[str, Any]]:
        """Return list of attachments for a message (includes contentBytes base64)."""
        url = f"{GRAPH_API_URL}/me/messages/{msg_id}/attachments"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("value", [])

    # -------------------- Signatures --------------------
    def list_signatures(self: OutlookClientBase) -> List[Dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self: OutlookClientBase, signature_html: str) -> None:
        raise NotImplementedError("Outlook signatures cannot be updated programmatically via Graph v1.0")
