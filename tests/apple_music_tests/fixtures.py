"""Shared test fixtures for apple_music tests."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional


class FakeResponse:
    """Fake HTTP response for mocking requests."""

    def __init__(self, body: dict, status: int = 200):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class FakeSession:
    """Fake HTTP session that returns queued responses."""

    def __init__(self, responses: List[FakeResponse]):
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def get(self, url: str, headers=None, params=None, json=None) -> FakeResponse:
        self.calls.append({"url": url, "params": params})
        if not self.responses:
            raise AssertionError("No response queued")
        return self.responses.pop(0)


class FakeAppleMusicClient:
    """Configurable fake AppleMusicClient for testing."""

    def __init__(
        self,
        *,
        playlists: Optional[List[dict]] = None,
        tracks: Optional[List[dict]] = None,
        tracks_by_playlist: Optional[Dict[str, List[dict]]] = None,
        storefront: str = "us",
        on_search: Optional[Callable[[str, str, int], List[dict]]] = None,
        on_create: Optional[Callable[[str, List[dict], Optional[str]], dict]] = None,
        on_delete: Optional[Callable[[str], dict]] = None,
    ):
        self.playlists = playlists or []
        self.tracks = tracks or []
        self.tracks_by_playlist = tracks_by_playlist or {}
        self.storefront = storefront
        self._on_search = on_search
        self._on_create = on_create
        self._on_delete = on_delete

        # Track calls for assertions
        self.search_calls: List[tuple] = []
        self.created: Optional[dict] = None
        self.deleted: List[str] = []

    def ping(self) -> dict:
        return {"data": [{"id": self.storefront}]}

    def list_library_playlists(self, limit: Optional[int] = None) -> List[dict]:
        return self.playlists

    def list_playlist_tracks(self, playlist_id: str, limit: Optional[int] = None) -> List[dict]:
        if self.tracks_by_playlist:
            return self.tracks_by_playlist.get(playlist_id, [])
        return self.tracks

    def search_songs(self, term: str, storefront: str, limit: int = 1) -> List[dict]:
        self.search_calls.append((term, storefront, limit))
        if self._on_search:
            return self._on_search(term, storefront, limit)
        # Default: return deterministic song from term
        return [{"id": f"id-{term.replace(' ', '-')}", "type": "songs", "attributes": {"name": term}}]

    def create_playlist(self, name: str, tracks: List[dict], description: Optional[str] = None) -> dict:
        result = {"name": name, "tracks": tracks, "description": description}
        self.created = result
        if self._on_create:
            return self._on_create(name, tracks, description)
        return result

    def delete_playlist(self, playlist_id: str) -> dict:
        self.deleted.append(playlist_id)
        if self._on_delete:
            return self._on_delete(playlist_id)
        return {"id": playlist_id}


def make_playlist(id: str, name: str, date_added: Optional[str] = None) -> dict:
    """Create a playlist dict for testing."""
    attrs = {"name": name}
    if date_added:
        attrs["dateAdded"] = date_added
    return {"id": id, "attributes": attrs}


def make_track(id: str, name: str, artist: str, album: str) -> dict:
    """Create a track dict for testing."""
    return {
        "id": id,
        "attributes": {
            "name": name,
            "artistName": artist,
            "albumName": album,
        },
    }
