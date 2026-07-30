"""Thin Apple Music API client for library playlist export."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from core.cli_errors import CLIError
from core.http import HttpClient


class AppleMusicCLIError(CLIError):
    """Raised when the Apple Music API returns an error."""


class AppleMusicClient:
    def __init__(
        self,
        developer_token: str,
        user_token: str,
        base_url: str = "https://api.music.apple.com",
        session: Optional[object] = None,
    ) -> None:
        self.developer_token = developer_token
        self.user_token = user_token
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(base_url, session=session)

    def _make_path(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        stripped = path.lstrip("/")
        if stripped.startswith("v1/"):
            return f"/{stripped}"
        return f"/v1/{stripped}"

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.developer_token}",
            "Music-User-Token": self.user_token,
        }

    def _get(self, path: str, params: Optional[Dict[str, object]] = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_body: dict) -> dict:
        return self._request("POST", path, json_body=json_body)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, object]] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        import requests as _requests  # noqa: PLC0415 - intentional lazy import

        path = self._make_path(path)
        try:
            resp = self._http.request(method, path, params=params, headers=self._auth_headers(), json=json_body)
        except _requests.exceptions.HTTPError as exc:
            r = exc.response
            status = r.status_code if r is not None else "?"
            body = r.text if r is not None else ""
            raise AppleMusicCLIError(f"{status} from Apple Music: {body}") from exc
        try:
            return resp.json()
        except Exception as exc:  # pragma: no cover - defensive
            raise AppleMusicCLIError(f"Invalid JSON from Apple Music: {resp.text}") from exc

    def _paginate(
        self, path: str, params: Optional[Dict[str, object]] = None, limit: Optional[int] = None
    ) -> Iterable[dict]:
        remaining = limit
        next_path: Optional[str] = path
        next_params = params or {}
        while next_path:
            data = self._get(next_path, params=next_params)
            for item in data.get("data", []):
                yield item
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return
            next_path = data.get("next")
            next_params = None  # next already encodes params

    def list_library_playlists(self, limit: Optional[int] = None) -> List[dict]:
        return list(self._paginate("me/library/playlists", params={"limit": limit} if limit else None, limit=limit))

    def list_playlist_tracks(self, playlist_id: str, limit: Optional[int] = None) -> List[dict]:
        path = f"me/library/playlists/{playlist_id}/tracks"
        return list(self._paginate(path, params={"limit": limit} if limit else None, limit=limit))

    def ping(self) -> dict:
        """Lightweight auth check; returns storefront info."""
        return self._get("me/storefront")

    def search_songs(self, term: str, storefront: str, limit: int = 5) -> List[dict]:
        params = {"term": term, "types": "songs", "limit": limit}
        return self._get(f"catalog/{storefront}/search", params=params).get("results", {}).get("songs", {}).get("data", [])

    def create_playlist(self, name: str, tracks: List[dict], description: Optional[str] = None) -> dict:
        body = {
            "attributes": {"name": name},
            "relationships": {"tracks": {"data": tracks}},
        }
        if description:
            body["attributes"]["description"] = description
        return self._post("me/library/playlists", json_body=body)

    def delete_playlist(self, playlist_id: str) -> dict:
        """Attempt to delete a library playlist."""
        return self._request("DELETE", f"me/library/playlists/{playlist_id}")
