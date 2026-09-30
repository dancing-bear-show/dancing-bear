"""Processors, producers, and output plumbing for the Apple Music CLI pipeline."""

from __future__ import annotations

import json as _json
from typing import Any, Callable

from core.cli_output import OutputConfig, OutputFormat, OutputWriter
from core.pipeline import BaseProducer, ResultEnvelope, SafeProcessor

from .cli_helpers import _output_json
from .cli_models import (
    ExportPlaylistResult,
    ExportRequest,
    ListPlaylistsRequest,
    PlaylistResult,
    TrackResult,
    TracksRequest,
)


# ---------------------------------------------------------------------------
# Processors (C2)
# ---------------------------------------------------------------------------


class ListPlaylistsProcessor(SafeProcessor[ListPlaylistsRequest, list[PlaylistResult]]):
    """Fetch and type-convert library playlists."""

    def _process_safe(self, payload: ListPlaylistsRequest) -> list[PlaylistResult]:
        raw = payload.client.list_library_playlists(limit=payload.limit)
        results: list[PlaylistResult] = []
        for pl in raw:
            attrs = pl.get("attributes") or {}
            results.append(PlaylistResult(
                id=pl.get("id") or "",
                name=attrs.get("name") or "",
                track_count=attrs.get("trackCount") or 0,
            ))
        return results


def _track_fields(tr: dict[str, Any]) -> dict[str, Any]:
    """Project one API track resource to the export JSON shape, keeping None values."""
    attrs = tr.get("attributes") or {}
    return {
        "id": tr.get("id"),
        "name": attrs.get("name"),
        "artist": attrs.get("artistName"),
        "album": attrs.get("albumName"),
        "duration_ms": attrs.get("durationInMillis"),
        "track_number": attrs.get("trackNumber"),
    }


class TracksProcessor(SafeProcessor[TracksRequest, list[TrackResult]]):
    """Fetch all tracks across all library playlists."""

    def _process_safe(self, payload: TracksRequest) -> list[TrackResult]:
        playlists = payload.client.list_library_playlists(limit=payload.playlist_limit)
        results: list[TrackResult] = []
        for pl in playlists:
            pl_name = (pl.get("attributes") or {}).get("name") or ""
            pl_id = pl.get("id") or ""
            for tr in payload.client.list_playlist_tracks(pl_id, limit=payload.track_limit):
                track = _track_fields(tr)
                results.append(TrackResult(
                    id=track["id"] or "",
                    title=track["name"] or "",
                    artist=track["artist"] or "",
                    album=track["album"] or "",
                    playlist_id=pl_id,
                    playlist_name=pl_name,
                    duration_ms=track["duration_ms"],
                    track_number=track["track_number"],
                ))
        return results


class ExportProcessor(SafeProcessor[ExportRequest, list[ExportPlaylistResult]]):
    """Export playlists with their full track lists."""

    def _process_safe(self, payload: ExportRequest) -> list[ExportPlaylistResult]:
        results: list[ExportPlaylistResult] = []
        for pl in payload.client.list_library_playlists(limit=payload.playlist_limit):
            attrs = pl.get("attributes") or {}
            tracks_raw = payload.client.list_playlist_tracks(
                pl["id"], limit=payload.track_limit
            )
            tracks = [_track_fields(tr) for tr in tracks_raw]
            results.append(ExportPlaylistResult(
                id=pl.get("id") or "",
                name=attrs.get("name") or "",
                description=(attrs.get("description") or {}).get("standard"),
                tracks=tracks,
            ))
        return results


# ---------------------------------------------------------------------------
# Producers (C2 + C6)
# ---------------------------------------------------------------------------


def _tracks_to_dict(payload: list[TrackResult]) -> dict[str, Any]:
    """Serialize typed track results to the CLI's JSON shape."""
    return {
        "tracks": [
            {
                "playlist_id": tr.playlist_id,
                "playlist_name": tr.playlist_name,
                "id": tr.id,
                "name": tr.title,
                "artist": tr.artist,
                "album": tr.album,
                "duration_ms": tr.duration_ms,
                "track_number": tr.track_number,
            }
            for tr in payload
        ]
    }


class ListPlaylistsProducer(BaseProducer):
    """Output typed playlist list."""

    def _produce_success(
        self,
        payload: list[PlaylistResult],
        diagnostics: dict[str, Any] | None,
    ) -> None:
        data = {"playlists": [{"id": pl.id, "name": pl.name} for pl in payload]}
        self._writer.print_data(data)


class TracksProducer(BaseProducer):
    """Output typed track list."""

    def _produce_success(
        self,
        payload: list[TrackResult],
        diagnostics: dict[str, Any] | None,
    ) -> None:
        self._writer.print_data(_tracks_to_dict(payload))


class ExportProducer(BaseProducer):
    """Output full playlist export."""

    def _produce_success(
        self,
        payload: list[ExportPlaylistResult],
        diagnostics: dict[str, Any] | None,
    ) -> None:
        data = {
            "playlists": [
                {
                    "id": ep.id,
                    "name": ep.name,
                    "description": ep.description,
                    "tracks": ep.tracks,
                }
                for ep in payload
            ]
        }
        self._writer.print_data(data)


# ---------------------------------------------------------------------------
# Output plumbing
# ---------------------------------------------------------------------------


class _JsonOutputWriter(OutputWriter):
    """OutputWriter that respects the --pretty flag for JSON indent."""

    def __init__(self, config: OutputConfig | None = None, pretty: bool = False) -> None:
        super().__init__(config)
        self._pretty = pretty

    def _print_json(self, data: Any) -> None:
        normalized = self._normalize_for_json(data)
        indent = 2 if self._pretty else None
        self.print(_json.dumps(normalized, indent=indent))


def _make_json_writer(args: Any) -> _JsonOutputWriter:
    """Build a JSON OutputWriter writing to stdout (file writes handled by _output_json)."""
    pretty = getattr(args, "pretty", False)
    config = OutputConfig(format=OutputFormat.JSON)
    return _JsonOutputWriter(config=config, pretty=pretty)


def _produce_and_write(
    envelope: ResultEnvelope[Any],
    producer: BaseProducer,
    args: Any,
    payload_to_dict: Callable[[Any], dict[str, Any]],
) -> int:
    """Produce output: use OutputWriter for stdout, _output_json for file writes.

    Args:
        envelope: Processed result envelope.
        producer: Producer instance (writes to stdout via writer).
        args: CLI args (checked for --out and --pretty).
        payload_to_dict: Callable (payload) -> dict for file-write path.

    Returns:
        0 on success, 2 on error.
    """
    if not envelope.ok():
        producer.produce(envelope)
        return 2
    out_path = getattr(args, "out", None)
    if out_path:
        # File write path: convert to dict and use _output_json (no open file handle leak)
        payload_dict = payload_to_dict(envelope.payload)
        return _output_json(args, payload_dict)
    # Stdout path: let the producer drive OutputWriter
    producer.produce(envelope)
    return 0
