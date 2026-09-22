"""Folder operations mixin for Outlook via Microsoft Graph."""

from __future__ import annotations

from typing import Any, Protocol

from .client import OutlookClientBase, _requests
from core.constants import GRAPH_API_URL

_NEXT_LINK = "@odata.nextLink"


class _FoldersHost(Protocol):
    """Complete self-type for FoldersMixin methods that call sibling methods.

    Declares what those methods need from OutlookClientBase/ConfigCacheMixin
    (cross-class requirements) plus FoldersMixin's own sibling methods.
    """

    # --- From OutlookClientBase / ConfigCacheMixin ---
    def _headers(self) -> dict[str, str]: ...
    def cfg_get_json(self, name: str, ttl: int = ...) -> Any | None: ...
    def cfg_put_json(self, name: str, data: Any) -> None: ...
    def cfg_clear(self) -> None: ...

    # --- FoldersMixin's own sibling methods ---
    def list_folders(self) -> list[dict[str, Any]]: ...
    def get_folder_id_map(self) -> dict[str, str]: ...
    def ensure_folder(self, name: str) -> str: ...
    def list_all_folders(
        self, ttl: int = ..., clear_cache: bool = ..., bypass_cache: bool = ...
    ) -> list[dict[str, Any]]: ...
    def get_folder_path_map(
        self, ttl: int = ..., clear_cache: bool = ..., bypass_cache: bool = ...
    ) -> dict[str, str]: ...
    def _ensure_child_folder(self, parent_id: str, seg: str) -> str: ...


class FoldersMixin:
    """Mixin providing mail folder operations.

    Requires OutlookClientBase methods: _headers, cfg_get_json, cfg_put_json, cfg_clear.
    """

    def list_folders(self: OutlookClientBase) -> list[dict[str, Any]]:
        url: str | None = f"{GRAPH_API_URL}/me/mailFolders"
        out: list[dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("value", []))
            url = data.get(_NEXT_LINK)
        return out

    def get_folder_id_map(self: "_FoldersHost") -> dict[str, str]:
        return {f.get("displayName", ""): f.get("id", "") for f in self.list_folders()}

    def ensure_folder(self: "_FoldersHost", name: str) -> str:
        m = self.get_folder_id_map()
        if name in m and m[name]:
            return m[name]
        body = {"displayName": name}
        m0 = self.get_folder_id_map()
        if name in m0 and m0[name]:
            return m0[name]
        for endpoint in [f"{GRAPH_API_URL}/me/mailFolders", f"{GRAPH_API_URL}/me/mailFolders/Inbox/childFolders"]:
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
        self: "_FoldersHost",
        ttl: int = 600,
        clear_cache: bool = False,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all folders including nested, using BFS traversal.

        ``bypass_cache`` skips the cache READ (the write still happens, so the
        fresh listing is available to later callers).  It exists because neither
        existing knob can express "give me the current state":

        - ``ttl=0`` means "no expiry check" and serves an entry of ANY age --
          the opposite of fresh. See ``cfg_get_json``, which guards on
          ``if ttl > 0``; a negative ttl fails that guard the same way.
        - ``clear_cache=True`` calls ``cfg_clear()``, which wipes the ENTIRE
          provider cache, including unrelated rule caches. Too blunt for a
          caller that only needs folders.

        Used by ``resolve_folder_path`` so a preview can compare against the
        same folder ids the apply will resolve.
        """
        if clear_cache:
            self.cfg_clear()
        cached = None if bypass_cache else self.cfg_get_json("folders_all", ttl)
        if isinstance(cached, list):
            return cached
        all_folders: dict[str, dict[str, Any]] = {}
        roots = self.list_folders()
        for f in roots:
            if f.get("id"):
                all_folders[f["id"]] = f
        queue = list(all_folders.keys())
        while queue:
            fid = queue.pop(0)
            r = _requests().get(
                f"{GRAPH_API_URL}/me/mailFolders/{fid}/childFolders",
                headers=self._headers(),
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
        self: "_FoldersHost",
        ttl: int = 600,
        clear_cache: bool = False,
        bypass_cache: bool = False,
    ) -> dict[str, str]:
        """Map full path (Parent/Child/Sub) to folder id.

        ``bypass_cache`` is forwarded to ``list_all_folders``; see its docstring
        for why neither ``ttl`` nor ``clear_cache`` can express "read fresh".
        """
        folders = self.list_all_folders(
            ttl=ttl, clear_cache=clear_cache, bypass_cache=bypass_cache
        )
        by_id = {f.get("id"): f for f in folders}
        parent = {fid: f.get("parentFolderId") for fid, f in by_id.items()}
        name = {fid: (f.get("displayName") or "") for fid, f in by_id.items()}
        path_map: dict[str, str] = {}
        cache: dict[str, str] = {}

        def build_path(fid: str) -> str:
            if fid in cache:
                return cache[fid]
            parts = []
            cur = fid
            seen: set[str] = set()
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

    def _ensure_child_folder(self: OutlookClientBase, parent_id: str, seg: str) -> str:
        """Ensure a child folder with name `seg` exists under `parent_id`. Returns child folder id."""
        r = _requests().get(
            f"{GRAPH_API_URL}/me/mailFolders/{parent_id}/childFolders",
            headers=self._headers(),
        )
        r.raise_for_status()
        kids = r.json().get("value", [])
        kid_id = next((k.get("id") for k in kids if (k.get("displayName") or "").lower() == seg.lower()), None)
        if kid_id:
            return kid_id
        r2 = _requests().post(
            f"{GRAPH_API_URL}/me/mailFolders/{parent_id}/childFolders",
            headers=self._headers(),
            json={"displayName": seg},
        )
        if r2.status_code == 409:
            r3 = _requests().get(
                f"{GRAPH_API_URL}/me/mailFolders/{parent_id}/childFolders",
                headers=self._headers(),
            )
            r3.raise_for_status()
            kids2 = r3.json().get("value", [])
            kid_id = next((k.get("id") for k in kids2 if (k.get("displayName") or "").lower() == seg.lower()), None)
            if not kid_id:
                kid_id = next((k.get("id") for k in kids2 if seg.lower() in (k.get("displayName") or "").lower()), None)
            return kid_id or ""
        r2.raise_for_status()
        return r2.json().get("id") or ""

    def resolve_folder_path(
        self: "_FoldersHost",
        path: str,
        ttl: int = 600,
        fresh: bool = True,
    ) -> str:
        """Resolve a nested folder path to its id WITHOUT creating anything.

        Returns ``""`` when the path does not exist.  The non-mutating counterpart
        to ``ensure_folder_path``, for callers that must not change the mailbox --
        previews above all.

        Reads FRESH by default (``bypass_cache=True``), which is the point: this
        exists because a preview resolving through a *stale* cached snapshot
        classified a rule differently from the apply, reporting "Would create" for
        a rule the live run treated as a no-op.  Reading the same stale snapshot
        here would leave that gap exactly as it was.

        ``bypass_cache`` rather than a ttl value, because ttl cannot express it:
        ``cfg_get_json`` guards on ``if ttl > 0``, so ``ttl=0`` (and any negative
        value) means "no expiry check" and serves an entry of ANY age -- the
        opposite of fresh.  Verified by probe: with a 2-hour-old snapshot planted,
        ``ttl=0`` made zero Graph calls and returned ``""`` for a folder that
        exists.  ``clear_cache=True`` would work but wipes the entire provider
        cache, including unrelated rule caches.

        Callers that genuinely want the cached map already have
        ``get_folder_path_map``; pass ``fresh=False`` here to reuse it.
        """
        # Normalise exactly as ``ensure_folder_path`` does before resolving, so
        # both sides agree on what a path means.  Without this, `Archive//News`,
        # `Archive/News/` and `/Archive/News` all missed the map lookup and
        # reported the folder absent, while the live apply resolved them fine --
        # reintroducing the preview/apply divergence this method exists to close.
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            raise ValueError("Folder path is empty")
        return self.get_folder_path_map(ttl=ttl, bypass_cache=fresh).get("/".join(parts), "")

    def ensure_folder_path(self: "_FoldersHost", path: str) -> str:
        """Ensure a nested folder path exists and return the leaf folder id.

        MUTATES: creates every missing segment.  Use ``resolve_folder_path`` from
        any code path that must not change the mailbox.
        """
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            raise ValueError("Folder path is empty")

        top_map = self.get_folder_id_map()
        parent_id = top_map.get(parts[0]) or self.ensure_folder(parts[0])

        for seg in parts[1:]:
            parent_id = self._ensure_child_folder(parent_id, seg)
            if not parent_id:
                return ""
        return parent_id or ""
