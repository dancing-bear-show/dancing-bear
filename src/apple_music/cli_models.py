"""Typed dataclasses for Apple Music CLI requests and results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import AppleMusicClient


# ---------------------------------------------------------------------------
# Result dataclasses (C1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaylistResult:
    """Typed result for a single library playlist."""

    id: str
    name: str
    track_count: int


@dataclass(frozen=True)
class TrackResult:
    """Typed result for a single track with playlist context."""

    id: str
    title: str
    artist: str
    album: str
    playlist_id: str
    playlist_name: str
    duration_ms: int | None
    track_number: int | None


@dataclass(frozen=True)
class ExportPlaylistResult:
    """Typed result for a playlist with full track list during export."""

    id: str
    name: str
    description: str | None
    tracks: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Request dataclasses (C2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListPlaylistsRequest:
    """Request for listing library playlists."""

    client: AppleMusicClient
    limit: int | None = None


@dataclass(frozen=True)
class TracksRequest:
    """Request for listing all tracks with playlist context."""

    client: AppleMusicClient
    playlist_limit: int | None = None
    track_limit: int | None = None


@dataclass(frozen=True)
class ExportRequest:
    """Request for full playlist+track export."""

    client: AppleMusicClient
    playlist_limit: int | None = None
    track_limit: int | None = None
