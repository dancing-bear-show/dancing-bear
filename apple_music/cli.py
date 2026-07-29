"""apple_music CLI — re-export shim.

Implementation lives in:
  - apple_music.cli_helpers: auth, client factory, JSON output helpers, PlaylistCreationConfig
  - apple_music.cli_playlist: artist constants, PRESETS dict, playlist operation helpers
"""

from __future__ import annotations

import sys

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .client import AppleMusicClient, AppleMusicError  # noqa: F401 — AppleMusicClient for mock-patch compat; AppleMusicError used in cmd_create except clause
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


def _get_client(args) -> AppleMusicClient:
    """Create an AppleMusicClient from args.

    Defined here (not delegated to cli_helpers) so tests can mock-patch
    apple_music.cli.AppleMusicClient without affecting the helpers module.
    """
    developer_token, user_token = _resolve_tokens(args)
    if not developer_token:
        print("Missing developer token. Provide --developer-token or set developer_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    if not user_token:
        print("Missing user token. Provide --user-token or set user_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    return AppleMusicClient(developer_token, user_token)


@app.command("ping", help="Verify tokens and return storefront info")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
def cmd_ping(args) -> int:
    """Verify tokens and return storefront info."""
    client = _get_client(args)
    resp = client.ping()
    payload = {"status": "ok", "storefront": resp.get("data", [{}])[0].get("id") if resp else None}
    return _output_json(args, payload)


@app.command("list", help="List playlists (id and name)")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_list(args) -> int:
    """List playlists (id and name)."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    payload = {"playlists": [{"id": pl.get("id"), "name": (pl.get("attributes") or {}).get("name")} for pl in playlists]}
    return _output_json(args, payload)


@app.command("tracks", help="List all tracks with playlist context")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_tracks(args) -> int:
    """List all tracks with playlist context."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    tracks_out = []
    for pl in playlists:
        pl_name = (pl.get("attributes") or {}).get("name")
        pl_id = pl.get("id")
        for tr in client.list_playlist_tracks(pl_id, limit=getattr(args, "track_limit", None)):
            attrs = tr.get("attributes", {}) or {}
            tracks_out.append({
                "playlist_id": pl_id,
                "playlist_name": pl_name,
                "id": tr.get("id"),
                "name": attrs.get("name"),
                "artist": attrs.get("artistName"),
                "album": attrs.get("albumName"),
                "duration_ms": attrs.get("durationInMillis"),
                "track_number": attrs.get("trackNumber"),
            })
    return _output_json(args, {"tracks": tracks_out})


@app.command("export", help="Export playlists and tracks")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
@app.argument("--track-limit", type=int, help="Maximum tracks per playlist to fetch")
def cmd_export(args) -> int:
    """Export playlists and tracks."""
    client = _get_client(args)
    playlists_out = []
    for pl in client.list_library_playlists(limit=getattr(args, "playlist_limit", None)):
        attrs = pl.get("attributes", {}) or {}
        tracks_raw = client.list_playlist_tracks(pl["id"], limit=getattr(args, "track_limit", None))
        tracks = []
        for tr in tracks_raw:
            tr_attrs = tr.get("attributes", {}) or {}
            tracks.append({
                "id": tr.get("id"),
                "name": tr_attrs.get("name"),
                "artist": tr_attrs.get("artistName"),
                "album": tr_attrs.get("albumName"),
                "duration_ms": tr_attrs.get("durationInMillis"),
                "track_number": tr_attrs.get("trackNumber"),
            })
        playlists_out.append({
            "id": pl.get("id"),
            "name": attrs.get("name"),
            "description": (attrs.get("description") or {}).get("standard"),
            "tracks": tracks,
        })
    return _output_json(args, {"playlists": playlists_out})


@app.command("create", help="Create a playlist from preset seeds")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--preset", choices=sorted(PRESETS), default="spanish", help="Preset seed bundle")
@app.argument("--name", help="Playlist name (defaults to preset)")
@app.argument("--description", help="Playlist description (defaults to preset)")
@app.argument("--count", type=int, default=20, help="How many seeds to include (<= len seeds)")
@app.argument("--storefront", help="Storefront code (default: from ping)")
@app.argument("--shuffle-seed", type=int, help="Deterministic shuffle seed (optional)")
def cmd_create(args) -> int:
    """Create a playlist from preset seeds."""
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
    except AppleMusicError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _output_json(args, payload)


@app.command("dedupe", help="Find (and optionally delete) duplicate playlists by name")
@app.argument("--config", help="Path to credentials.ini (optional)")
@app.argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
@app.argument("--user-token", help="Music user token (overrides credentials.ini / env)")
@app.argument("--out", help="Path to write JSON output (default stdout)")
@app.argument("--pretty", action="store_true", help="Pretty-print JSON")
@app.argument("--keep", choices=["latest", "first"], default="latest", help="Which duplicate to keep")
@app.argument("--delete", action="store_true", help="Delete duplicates (default: plan only)")
@app.argument("--playlist-limit", type=int, help="Maximum playlists to fetch")
def cmd_dedupe(args) -> int:
    """Find (and optionally delete) duplicate playlists by name."""
    client = _get_client(args)
    playlists = client.list_library_playlists(limit=getattr(args, "playlist_limit", None))
    by_name: dict[str, list[dict]] = {}
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
