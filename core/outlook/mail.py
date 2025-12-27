"""Mail operations for Outlook via Microsoft Graph.

Includes categories (labels), rules (filters), messages, and folders.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .client import OutlookClientBase, _requests, GRAPH


class OutlookMailMixin:
    """Mixin providing mail operations (categories, rules, messages, folders).

    Requires OutlookClientBase methods: _headers, _headers_search, cfg_get_json, cfg_put_json, cfg_clear
    """

    # -------------------- Categories (labels) --------------------
    def list_labels(
        self: OutlookClientBase,
        use_cache: bool = False,
        ttl: int = 300
    ) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("categories", ttl)
            if isinstance(cached, list):
                cats = cached
            else:
                r = _requests().get(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers())
                r.raise_for_status()
                cats = r.json().get("value", [])
                self.cfg_put_json("categories", cats)
        else:
            r = _requests().get(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers())
            r.raise_for_status()
            cats = r.json().get("value", [])
        out = []
        for c in cats:
            entry = {
                "id": c.get("id"),
                "name": c.get("displayName"),
                "color": {"name": c.get("color")},
                "type": "user",
            }
            out.append(entry)
        return out

    def create_label(
        self: OutlookClientBase,
        name: str,
        color: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        body = {"displayName": name}
        if color and isinstance(color, dict) and color.get("name"):
            body["color"] = color.get("name")
        r = _requests().post(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers(), json=body)
        r.raise_for_status()
        c = r.json()
        return {"id": c.get("id"), "name": c.get("displayName")}

    def update_label(
        self: OutlookClientBase,
        label_id: str,
        body: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if body.get("name"):
            payload["displayName"] = body["name"]
        if isinstance(body.get("color"), dict) and body["color"].get("name"):
            payload["color"] = body["color"]["name"]
        if not payload:
            return {}
        r = _requests().patch(
            f"{GRAPH}/me/outlook/masterCategories/{label_id}",
            headers=self._headers(),
            json=payload
        )
        r.raise_for_status()
        return r.json() if r.text else {}

    def delete_label(self: OutlookClientBase, label_id: str) -> None:
        r = _requests().delete(
            f"{GRAPH}/me/outlook/masterCategories/{label_id}",
            headers=self._headers()
        )
        r.raise_for_status()

    def get_label_id_map(self: OutlookClientBase) -> Dict[str, str]:
        return {lbl.get("name", ""): lbl.get("id", "") for lbl in self.list_labels()}

    def ensure_label(self: OutlookClientBase, name: str, **kwargs: Any) -> str:
        m = self.get_label_id_map()
        if name in m:
            return m[name]
        created = self.create_label(name, **kwargs)
        return created.get("id", "")

    # -------------------- Rules (filters) --------------------
    def list_filters(
        self: OutlookClientBase,
        use_cache: bool = False,
        ttl: int = 300
    ) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("rules_inbox", ttl)
            if isinstance(cached, list):
                rules = cached
            else:
                r = _requests().get(
                    f"{GRAPH}/me/mailFolders/inbox/messageRules",
                    headers=self._headers()
                )
                r.raise_for_status()
                rules = r.json().get("value", [])
                self.cfg_put_json("rules_inbox", rules)
        else:
            r = _requests().get(
                f"{GRAPH}/me/mailFolders/inbox/messageRules",
                headers=self._headers()
            )
            r.raise_for_status()
            rules = r.json().get("value", [])
        mapped: List[Dict[str, Any]] = []
        for ru in rules:
            cond = ru.get("conditions", {}) or {}
            act = ru.get("actions", {}) or {}
            crit: Dict[str, Any] = {}
            if cond.get("senderContains"):
                crit["from"] = " OR ".join(cond["senderContains"])
            if cond.get("recipientContains"):
                crit["to"] = " OR ".join(cond["recipientContains"])
            if cond.get("subjectContains"):
                crit["subject"] = " OR ".join(cond["subjectContains"])
            action: Dict[str, Any] = {}
            if act.get("assignCategories"):
                action["addLabelIds"] = act["assignCategories"]
            if act.get("forwardTo"):
                action["forward"] = ",".join([
                    a.get("emailAddress", {}).get("address", "")
                    for a in act["forwardTo"]
                ])
            if act.get("moveToFolder"):
                action["moveToFolderId"] = act.get("moveToFolder")
            mapped.append({"id": ru.get("id"), "criteria": crit, "action": action})
        return mapped

    def create_filter(
        self: OutlookClientBase,
        criteria: Dict[str, Any],
        action: Dict[str, Any]
    ) -> Dict[str, Any]:
        cond: Dict[str, Any] = {}
        if criteria.get("from"):
            cond["senderContains"] = [s.strip() for s in str(criteria["from"]).split("OR")]
        if criteria.get("to"):
            cond["recipientContains"] = [s.strip() for s in str(criteria["to"]).split("OR")]
        if criteria.get("subject"):
            cond["subjectContains"] = [s.strip() for s in str(criteria["subject"]).split("OR")]
        act: Dict[str, Any] = {}
        if action.get("addLabelIds"):
            act["assignCategories"] = action["addLabelIds"]
        if action.get("forward"):
            emails = [e.strip() for e in str(action["forward"]).split(",") if e.strip()]
            act["forwardTo"] = [{"emailAddress": {"address": e}} for e in emails]
        if action.get("moveToFolderId"):
            act["moveToFolder"] = action["moveToFolderId"]
        payload = {
            "displayName": f"Rule {int(time.time())}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": cond,
            "actions": act,
            "stopProcessingRules": True,
        }
        r = _requests().post(
            f"{GRAPH}/me/mailFolders/inbox/messageRules",
            headers=self._headers(),
            json=payload
        )
        r.raise_for_status()
        return r.json()

    def delete_filter(self: OutlookClientBase, filter_id: str) -> None:
        r = _requests().delete(
            f"{GRAPH}/me/mailFolders/inbox/messageRules/{filter_id}",
            headers=self._headers()
        )
        r.raise_for_status()

    # -------------------- Messages --------------------
    def search_inbox_messages(
        self: OutlookClientBase,
        search_query: str,
        days: Optional[int] = None,
        top: int = 25,
        pages: int = 2,
        use_cache: bool = True,
        ttl: int = 300,
    ) -> List[str]:
        """Return message IDs in Inbox matching $search query, optional days filter."""
        if self.cache_dir and use_cache:
            import hashlib
            key = f"search_{hashlib.sha256(f'{search_query}|{top}|{pages}|{days}'.encode()).hexdigest()}"
            cached = self.cfg_get_json(key, ttl)
            if isinstance(cached, list):
                return [str(x) for x in cached]
        ids: List[str] = []
        base = f"{GRAPH}/me/mailFolders/inbox/messages"
        params = [f"$search=\"{search_query}\"", f"$top={int(top)}"]
        if days and int(days) > 0:
            import datetime as _dt
            start = _dt.datetime.utcnow() - _dt.timedelta(days=int(days))
            start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            params.append(f"$filter=receivedDateTime ge {start_iso}")
        url = base + "?" + "&".join(params)
        nxt = url
        for _ in range(max(1, int(pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            vals = data.get("value", [])
            for m in vals:
                mid = m.get("id")
                if mid:
                    ids.append(mid)
            nxt = data.get("@odata.nextLink")
            if not nxt:
                break
        if self.cache_dir and use_cache:
            try:
                self.cfg_put_json(key, ids)
            except Exception:  # noqa: S110 - non-fatal cache write
                pass
        return ids

    def list_messages(
        self: OutlookClientBase,
        folder: str = "inbox",
        top: int = 25,
        pages: int = 1,
    ) -> List[Dict[str, Any]]:
        """List messages in a folder with pagination."""
        base = f"{GRAPH}/me/mailFolders/{folder}/messages"
        url = f"{base}?$top={int(top)}&$orderby=receivedDateTime desc"
        msgs: List[Dict[str, Any]] = []
        for _ in range(max(1, int(pages))):
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            msgs.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if not url:
                break
        return msgs

    def move_message(self: OutlookClientBase, msg_id: str, dest_folder_id: str) -> None:
        body = {"destinationId": dest_folder_id}
        r = _requests().post(
            f"{GRAPH}/me/messages/{msg_id}/move",
            headers=self._headers(),
            json=body
        )
        r.raise_for_status()

    def get_message(
        self: OutlookClientBase,
        msg_id: str,
        select_body: bool = True
    ) -> Dict[str, Any]:
        sel = "$select=subject,receivedDateTime,from,bodyPreview" + (",body" if select_body else "")
        url = f"{GRAPH}/me/messages/{msg_id}?{sel}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    # -------------------- Folders --------------------
    def list_folders(self: OutlookClientBase) -> List[Dict[str, Any]]:
        url = f"{GRAPH}/me/mailFolders"
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return out

    def get_folder_id_map(self: OutlookClientBase) -> Dict[str, str]:
        return {f.get("displayName", ""): f.get("id", "") for f in self.list_folders()}

    def ensure_folder(self: OutlookClientBase, name: str) -> str:
        m = self.get_folder_id_map()
        if name in m and m[name]:
            return m[name]
        body = {"displayName": name}
        m0 = self.get_folder_id_map()
        if name in m0 and m0[name]:
            return m0[name]
        for endpoint in [f"{GRAPH}/me/mailFolders", f"{GRAPH}/me/mailFolders/Inbox/childFolders"]:
            r = _requests().post(endpoint, headers=self._headers(), json=body)
            if r.status_code == 409:
                m2 = self.get_folder_id_map()
                if name in m2 and m2[name]:
                    return m2[name]
            if 200 <= r.status_code < 300:
                f = r.json()
                return f.get("id", "")
        r.raise_for_status()
        f = r.json()
        return f.get("id", "")

    def list_all_folders(
        self: OutlookClientBase,
        ttl: int = 600,
        clear_cache: bool = False
    ) -> List[Dict[str, Any]]:
        """Return all folders including nested, using BFS traversal."""
        if clear_cache:
            self.cfg_clear()
        cached = self.cfg_get_json("folders_all", ttl)
        if isinstance(cached, list):
            return cached
        all_folders: Dict[str, Dict[str, Any]] = {}
        roots = self.list_folders()
        for f in roots:
            if f.get("id"):
                all_folders[f["id"]] = f
        queue = list(all_folders.keys())
        while queue:
            fid = queue.pop(0)
            r = _requests().get(
                f"{GRAPH}/me/mailFolders/{fid}/childFolders",
                headers=self._headers()
            )
            r.raise_for_status()
            for ch in r.json().get("value", []):
                cid = ch.get("id")
                if cid and cid not in all_folders:
                    all_folders[cid] = ch
                    queue.append(cid)
        vals = list(all_folders.values())
        self.cfg_put_json("folders_all", vals)
        return vals

    def get_folder_path_map(
        self: OutlookClientBase,
        ttl: int = 600,
        clear_cache: bool = False
    ) -> Dict[str, str]:
        """Map full path (Parent/Child/Sub) to folder id."""
        folders = self.list_all_folders(ttl=ttl, clear_cache=clear_cache)
        by_id = {f.get("id"): f for f in folders}
        parent = {fid: f.get("parentFolderId") for fid, f in by_id.items()}
        name = {fid: (f.get("displayName") or "") for fid, f in by_id.items()}
        path_map: Dict[str, str] = {}
        cache: Dict[str, str] = {}

        def build_path(fid: str) -> str:
            if fid in cache:
                return cache[fid]
            parts = []
            cur = fid
            seen = set()
            while cur and cur in name and cur not in seen:
                seen.add(cur)
                parts.append(name[cur])
                cur = parent.get(cur)
            parts.reverse()
            p = "/".join([p for p in parts if p])
            cache[fid] = p
            return p

        for fid in by_id:
            p = build_path(fid)
            if p:
                path_map[p] = fid
        self.cfg_put_json("folders_path_map", path_map)
        return path_map

    def ensure_folder_path(self: OutlookClientBase, path: str) -> str:
        """Ensure a nested folder path exists and return the leaf folder id."""
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            raise ValueError("Folder path is empty")

        parent_id: Optional[str] = None
        top_map = self.get_folder_id_map()
        if parts[0] in top_map and top_map[parts[0]]:
            parent_id = top_map[parts[0]]
        else:
            parent_id = self.ensure_folder(parts[0])

        for seg in parts[1:]:
            r = _requests().get(
                f"{GRAPH}/me/mailFolders/{parent_id}/childFolders",
                headers=self._headers()
            )
            r.raise_for_status()
            kids = r.json().get("value", [])
            kid_id = next((k.get("id") for k in kids if k.get("displayName") == seg), None)
            if kid_id:
                parent_id = kid_id
                continue
            body = {"displayName": seg}
            r2 = _requests().post(
                f"{GRAPH}/me/mailFolders/{parent_id}/childFolders",
                headers=self._headers(),
                json=body
            )
            r2.raise_for_status()
            created = r2.json()
            parent_id = created.get("id")
        return parent_id or ""

    # -------------------- Signatures --------------------
    def list_signatures(self: OutlookClientBase) -> List[Dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self: OutlookClientBase, signature_html: str) -> None:
        raise NotImplementedError("Outlook signatures cannot be updated programmatically via Graph v1.0")
