"""Shared test fixtures for apple_music tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from requests.exceptions import HTTPError


class FakeResponse:
    """Fake HTTP response for mocking requests."""

    def __init__(self, body: dict, status: int = 200):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
        self.content = self.text.encode()
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    """Fake HTTP session that returns queued responses."""

    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs) -> FakeResponse:  # NOSONAR - fake interface must match real signature  # fmt: skip
        self.calls.append({"method": method, "url": url, "params": kwargs.get("params")})
        if not self.responses:
            raise AssertionError("No response queued")
        return self.responses.pop(0)

    def get(self, url: str, headers=None, params=None, **kwargs) -> FakeResponse:  # NOSONAR - kept for backward compat  # fmt: skip
        return self.request("GET", url, params=params)


class FakeAppleMusicClient:
    """Configurable fake AppleMusicClient for testing."""

    def __init__(
        self,
        *,
        playlists: list[dict] | None = None,
        tracks: list[dict] | None = None,
        storefront: str = "us",
        **kwargs,
    ):
        """Optional kwargs: tracks_by_playlist, on_search, on_create, on_delete."""
        self.playlists = playlists or []
        self.tracks = tracks or []
        self.tracks_by_playlist: dict[str, list[dict]] = kwargs.get("tracks_by_playlist") or {}
        self.storefront = storefront
        self._on_search: Callable | None = kwargs.get("on_search")
        self._on_create: Callable | None = kwargs.get("on_create")
        self._on_delete: Callable | None = kwargs.get("on_delete")

        # Track calls for assertions
        self.search_calls: list[tuple] = []
        self.created: dict | None = None
        self.deleted: list[str] = []

    def ping(self) -> dict:
        return {"data": [{"id": self.storefront}]}

    def list_library_playlists(self, limit: int | None = None) -> list[dict]:  # NOSONAR - fake interface must match real signature  # fmt: skip
        return self.playlists

    def list_playlist_tracks(self, playlist_id: str, limit: int | None = None) -> list[dict]:  # NOSONAR - fake interface must match real signature  # fmt: skip
        if self.tracks_by_playlist:
            return self.tracks_by_playlist.get(playlist_id, [])
        return self.tracks

    def search_songs(self, term: str, storefront: str, limit: int = 1) -> list[dict]:
        self.search_calls.append((term, storefront, limit))
        if self._on_search:
            return self._on_search(term, storefront, limit)
        # Default: return deterministic song from term
        return [
            {"id": f"id-{term.replace(' ', '-')}", "type": "songs", "attributes": {"name": term}}
        ]

    def create_playlist(
        self, name: str, tracks: list[dict], description: str | None = None
    ) -> dict:
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


def make_playlist(id: str, name: str, date_added: str | None = None) -> dict:
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
