"""apple_music CLI — re-export shim.

Implementation lives in:
  - apple_music.cli_helpers: auth, client factory, JSON output helpers, PlaylistCreationConfig
  - apple_music.cli_playlist: artist constants, PRESETS dict, playlist operation helpers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.assistant import BaseAssistant
from core.cli_errors import AuthError
from core.cli_framework import CLIApp
from core.cli_help_text import HELP_JSON_OUT, HELP_PRETTY_JSON
from core.cli_output import OutputConfig, OutputFormat, OutputWriter
from core.pipeline import BaseProducer, ResultEnvelope, SafeProcessor

from .client import AppleMusicCLIError, AppleMusicClient  # noqa: F401 — AppleMusicClient for mock-patch compat
from .cli_helpers import (  # noqa: F401
    PlaylistCreationConfig,
    _output_json,
    _resolve_tokens,
)
from .cli_playlist import (  # noqa: F401
    ALIZEE,
    GIPSY_KINGS,
    GREAT_BIG_SEA,
    JUAN_LUIS_GUERRA,
    KNIFE_PARTY,
    LINKIN_PARK,
    LIMP_BIZKIT,
    MYLENE_FARMER,
    PRESETS,
    RAGE_AGAINST_THE_MACHINE,
    SMASHING_PUMPKINS,
    STAN_ROGERS,
    SYSTEM_OF_A_DOWN,
    THE_LONGEST_JOHNS,
    _create_from_seeds,
    _delete_duplicate_playlists,
    _parse_playlist_date,
    _playlist_sort_key,
)

# ---------------------------------------------------------------------------
# Dataclasses (C1)
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
# Requests (C2)
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


class TracksProcessor(SafeProcessor[TracksRequest, list[TrackResult]]):
    """Fetch all tracks across all library playlists."""

    def _process_safe(self, payload: TracksRequest) -> list[TrackResult]:
        playlists = payload.client.list_library_playlists(limit=payload.playlist_limit)
        results: list[TrackResult] = []
        for pl in playlists:
            pl_name = (pl.get("attributes") or {}).get("name") or ""
            pl_id = pl.get("id") or ""
            for tr in payload.client.list_playlist_tracks(pl_id, limit=payload.track_limit):
                attrs = tr.get("attributes") or {}
                results.append(TrackResult(
                    id=tr.get("id") or "",
                    title=attrs.get("name") or "",
                    artist=attrs.get("artistName") or "",
                    album=attrs.get("albumName") or "",
                    playlist_id=pl_id,
                    playlist_name=pl_name,
                    duration_ms=attrs.get("durationInMillis"),
                    track_number=attrs.get("trackNumber"),
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
            tracks = []
            for tr in tracks_raw:
                tr_attrs = tr.get("attributes") or {}
                tracks.append({
                    "id": tr.get("id"),
                    "name": tr_attrs.get("name"),
                    "artist": tr_attrs.get("artistName"),
                    "album": tr_attrs.get("albumName"),
                    "duration_ms": tr_attrs.get("durationInMillis"),
                    "track_number": tr_attrs.get("trackNumber"),
                })
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
        diagnostics: Optional[dict[str, Any]],
    ) -> None:
        data = {"playlists": [{"id": pl.id, "name": pl.name} for pl in payload]}
        self._writer.print_data(data)


class TracksProducer(BaseProducer):
    """Output typed track list."""

    def _produce_success(
        self,
        payload: list[TrackResult],
        diagnostics: Optional[dict[str, Any]],
    ) -> None:
        self._writer.print_data(_tracks_to_dict(payload))


class ExportProducer(BaseProducer):
    """Output full playlist export."""

    def _produce_success(
        self,
        payload: list[ExportPlaylistResult],
        diagnostics: Optional[dict[str, Any]],
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
# CLI app
# ---------------------------------------------------------------------------

# Create the CLI app
app = CLIApp(
    "apple-music-assistant",
    "Apple Music assistant CLI for playlist management.",
    add_common_args=True,
)

_assistant = BaseAssistant(
    "apple-music-assistant",
    "agentic: apple-music-assistant\npurpose: Apple Music playlist management",
)


class _JsonOutputWriter(OutputWriter):
    """OutputWriter that respects the --pretty flag for JSON indent."""

    def __init__(self, config: OutputConfig | None = None, pretty: bool = False) -> None:
        super().__init__(config)
        self._pretty = pretty

    def _print_json(self, data: Any) -> None:
        import json as _json

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
    payload_to_dict: Any,
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


def _get_client(args: Any) -> AppleMusicClient:
    """Create an AppleMusicClient from args.

    Defined here (not delegated to cli_helpers) so tests can mock-patch
    apple_music.cli.AppleMusicClient without affecting the helpers module.
    """
    developer_token, user_token = _resolve_tokens(args)
    if not developer_token:
        raise AuthError(
            "Missing developer token. Provide --developer-token or set developer_token in credentials.ini."
        )
    if not user_token:
        raise AuthError(
            "Missing user token. Provide --user-token or set user_token in credentials.ini."
        )
    return AppleMusicClient(developer_token, user_token)


@app.command("ping", help="Verify tokens and return storefront info")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
def cmd_ping(args: Any) -> int:
    """Verify tokens and return storefront info."""
    client = _get_client(args)
    resp = client.ping()
    payload = {"status": "ok", "storefront": resp.get("data", [{}])[0].get("id") if resp else None}
    return _output_json(args, payload)


@app.command("list", help="List playlists (id and name)")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_list(args: Any) -> int:
    """List playlists (id and name)."""
    client = _get_client(args)
    request = ListPlaylistsRequest(
        client=client,
        limit=getattr(args, "playlist_limit", None),
    )
    envelope: ResultEnvelope[list[PlaylistResult]] = ListPlaylistsProcessor().process(request)
    writer = _make_json_writer(args)
    return _produce_and_write(
        envelope,
        ListPlaylistsProducer(writer),
        args,
        lambda payload: {"playlists": [{"id": pl.id, "name": pl.name} for pl in payload]},
    )


@app.command("tracks", help="List all tracks with playlist context")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_tracks(args: Any) -> int:
    """List all tracks with playlist context."""
    client = _get_client(args)
    request = TracksRequest(
        client=client,
        playlist_limit=getattr(args, "playlist_limit", None),
        track_limit=getattr(args, "track_limit", None),
    )
    envelope: ResultEnvelope[list[TrackResult]] = TracksProcessor().process(request)
    writer = _make_json_writer(args)

    return _produce_and_write(envelope, TracksProducer(writer), args, _tracks_to_dict)


@app.command("export", help="Export playlists and tracks")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_export(args: Any) -> int:
    """Export playlists and tracks."""
    client = _get_client(args)
    request = ExportRequest(
        client=client,
        playlist_limit=getattr(args, "playlist_limit", None),
        track_limit=getattr(args, "track_limit", None),
    )
    envelope: ResultEnvelope[list[ExportPlaylistResult]] = ExportProcessor().process(request)
    writer = _make_json_writer(args)

    def _export_to_dict(payload: list[ExportPlaylistResult]) -> dict[str, Any]:
        return {
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

    return _produce_and_write(envelope, ExportProducer(writer), args, _export_to_dict)


@app.command("create", help="Create a playlist from preset seeds")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
@app.argument("--preset", choices=sorted(PRESETS), default="spanish", help="Preset seed bundle")
@app.argument("--name", help="Playlist name (defaults to preset)")
@app.argument("--description", help="Playlist description (defaults to preset)")
@app.argument("--count", type=int, default=20, help="How many seeds to include (<= len seeds)")
@app.argument("--storefront", help="Storefront code (default: from ping)")
@app.argument("--shuffle-seed", type=int, help="Deterministic shuffle seed (optional)")
def cmd_create(args: Any) -> int:
    """Create a playlist from preset seeds."""
    import sys

    client = _get_client(args)
    preset = PRESETS[args.preset]
    name = getattr(args, "name", None) or preset["name"]
    desc = args.description if getattr(args, "description", None) is not None else preset["description"]
    config = PlaylistCreationConfig(
        name=name,
        description=desc,
        count=args.count,
        shuffle_seed=getattr(args, "shuffle_seed", None),
        storefront=getattr(args, "storefront", None),
        dry_run=getattr(args, "dry_run", False),
    )
    try:
        payload = _create_from_seeds(
            client=client,
            seeds=preset["seeds"],
            config=config,
        )
    except AppleMusicCLIError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _output_json(args, payload)


@app.command("dedupe", help="Find (and optionally delete) duplicate playlists by name")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help=HELP_JSON_OUT)
@app.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
@app.argument("--keep", choices=["latest", "first"], default="latest", help="Which duplicate to keep")
@app.argument("--delete", action="store_true", help="Delete duplicates (default: plan only)")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_dedupe(args: Any) -> int:
    """Find (and optionally delete) duplicate playlists by name."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    by_name: dict[str, list[dict[str, Any]]] = {}
    for pl in playlists:
        name = (pl.get("attributes") or {}).get("name") or ""
        by_name.setdefault(name, []).append(pl)

    do_delete = getattr(args, "delete", False)
    plan = []
    deleted: list[str] = []
    for name, pls in by_name.items():
        if len(pls) <= 1:
            continue
        sorted_pls = sorted(pls, key=_playlist_sort_key, reverse=args.keep == "latest")
        keep = sorted_pls[0]
        remove = sorted_pls[1:]
        plan.append({
            "name": name,
            "keep": keep.get("id"),
            "remove": [p.get("id") for p in remove],
        })
        if do_delete:
            deleted.extend(_delete_duplicate_playlists(client, remove))

    payload = {"duplicates": plan, "deleted": deleted if do_delete else []}
    return _output_json(args, payload)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    return app.run_with_assistant(
        _assistant,
        emit_func=lambda fmt, compact: (print(_assistant.fallback_banner) or 0),
        argv=argv,
    )
