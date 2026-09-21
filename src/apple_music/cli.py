"""apple_music CLI — argument parsing and command handlers.

Owns main(), the CLIApp wiring, and the token/ping/list/tracks/export/create/
dedupe handlers. Supporting pieces it draws on:
  - apple_music.cli_helpers: auth, client factory, JSON output helpers, PlaylistCreationConfig
  - apple_music.cli_models: typed result and request dataclasses
  - apple_music.cli_pipeline: processors, producers, and output plumbing
  - apple_music.cli_playlist: artist constants, PRESETS dict, playlist operation helpers
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from core.assistant import BaseAssistant
from core.cli_errors import AuthError, ConfigError
from core.cli_framework import CLIApp
from core.cli_help_text import HELP_JSON_OUT, HELP_PRETTY_JSON
from core.pipeline import ResultEnvelope

from .client import AppleMusicCLIError, AppleMusicClient  # noqa: F401 — AppleMusicClient for mock-patch compat
from .cli_helpers import (  # noqa: F401
    PlaylistCreationConfig,
    _format_timestamp,
    _output_json,
    _resolve_tokens,
    save_credential_value,
)
from .cli_models import (
    ExportPlaylistResult,
    ExportRequest,
    ListPlaylistsRequest,
    PlaylistResult,
    TrackResult,
    TracksRequest,
)
from .cli_pipeline import (
    ExportProcessor,
    ExportProducer,
    ListPlaylistsProcessor,
    ListPlaylistsProducer,
    TracksProcessor,
    TracksProducer,
    _make_json_writer,
    _produce_and_write,
    _tracks_to_dict,
)
from .config import DEFAULT_PROFILE, load_profile
from .developer_token import MAX_TTL_DAYS, SECONDS_PER_DAY, decode_claims, mint_developer_token
from .meta import META
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
# CLI app
# ---------------------------------------------------------------------------

# Create the CLI app
app = CLIApp(
    "apple-music-assistant",
    "Apple Music assistant CLI for playlist management.",
    add_common_args=True,
)

_assistant = BaseAssistant(META.app_id, META.agentic_fallback)


@lru_cache(maxsize=1)
def _lazy_agentic() -> Callable[[str, bool], int]:
    """Return the capsule emitter, importing it on first use.

    Deferred so the agentic module is not imported on every CLI invocation.
    The signature matches emit_agentic_context(fmt, compact) -> int, which the
    CLI wiring calls positionally.
    """
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


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


token_group = app.group("token", help="Manage Apple Music tokens")


@token_group.command("mint", help="Mint a developer token from the MusicKit .p8 key")
@token_group.argument("--config", help="Path to credentials.ini (optional)")
@token_group.argument("--key-path", help="Path to the MusicKit .p8 key (overrides credentials.ini)")
@token_group.argument("--team-id", help="Apple Developer team ID (overrides credentials.ini)")
@token_group.argument("--key-id", help="MusicKit key ID (overrides credentials.ini)")
@token_group.argument("--ttl-days", type=int, default=MAX_TTL_DAYS, help=f"Token lifetime in days (max {MAX_TTL_DAYS})")
@token_group.argument("--save", action="store_true", help="Write the token back to credentials.ini")
@token_group.argument("--out", help=HELP_JSON_OUT)
@token_group.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
def cmd_token_mint(args: Any) -> int:
    """Mint a developer token from the MusicKit .p8 key."""
    profile = getattr(args, "profile", None) or DEFAULT_PROFILE
    config_path, profile_cfg = load_profile(profile, getattr(args, "config", None))
    key_path = getattr(args, "key_path", None) or profile_cfg.get("key_path")
    if not key_path:
        raise ConfigError(
            "Missing key_path.",
            hint="Set key_path in the credentials.ini profile or pass --key-path.",
        )
    token = mint_developer_token(
        key_path=key_path,
        team_id=getattr(args, "team_id", None) or profile_cfg.get("team_id", ""),
        key_id=getattr(args, "key_id", None) or profile_cfg.get("key_id", ""),
        ttl_seconds=args.ttl_days * SECONDS_PER_DAY,
    )
    claims = decode_claims(token)
    saved_to = None
    if getattr(args, "save", False):
        if config_path is None:
            raise ConfigError(
                f"Cannot save: no credentials.ini defines profile [{profile}].",
                hint="Create the profile first, or omit --save and copy the token manually.",
            )
        save_credential_value(config_path, profile, "developer_token", token)
        saved_to = str(config_path)

    payload = {
        "expires_at": _format_timestamp(claims.expires_at),
        "key_id": claims.key_id,
        "saved_to": saved_to,
        "profile": profile if saved_to else None,
    }
    # Only echo the secret when it is not being persisted for the user.
    if saved_to is None:
        payload["developer_token"] = token
    return _output_json(args, payload)


def _verify_tokens_live(developer_token: str | None, user_token: str | None) -> dict[str, Any]:
    """Call Apple to distinguish a working token pair from a merely present one.

    Apple answers a bad developer token with 401 and a bad user token with 403, so the
    status code identifies which credential needs renewing.
    """
    if not developer_token or not user_token:
        return {"verified": False, "error": "both tokens must be present to verify"}
    try:
        AppleMusicClient(developer_token, user_token).ping()
    except AppleMusicCLIError as exc:
        message = str(exc)
        if "401" in message:
            remedy = "developer token rejected; run: apple-music-assistant token mint --save"
        elif "403" in message:
            remedy = (
                "user token rejected (often orphaned by a new key); "
                "run: bin/apple-music-user-token --serve --save"
            )
        else:
            remedy = "see error"
        return {"verified": False, "error": message, "remedy": remedy}
    return {"verified": True}


@token_group.command("status", help="Report token expiry and verify both tokens against Apple")
@token_group.argument("--config", help="Path to credentials.ini (optional)")
@token_group.argument("--offline", action="store_true", help="Skip the live API check")
@token_group.argument("--out", help=HELP_JSON_OUT)
@token_group.argument("--pretty", action="store_true", help=HELP_PRETTY_JSON)
def cmd_token_status(args: Any) -> int:
    """Report token expiry and verify both tokens against Apple."""
    developer_token, user_token = _resolve_tokens(args)
    payload: dict[str, Any] = {
        "developer_token": {"present": bool(developer_token)},
        "user_token": {"present": bool(user_token)},
    }
    if developer_token:
        claims = decode_claims(developer_token)
        remaining = claims.seconds_remaining()
        payload["developer_token"].update({
            "key_id": claims.key_id,
            "issued_at": _format_timestamp(claims.issued_at),
            "expires_at": _format_timestamp(claims.expires_at),
            "expired": claims.is_expired(),
            "days_remaining": remaining // SECONDS_PER_DAY if remaining is not None else None,
        })

    # A user token carries no expiry to inspect, and an orphaned one (issued under a
    # replaced key) still looks present while every call fails. Only a live call can
    # tell the difference, so verify unless explicitly asked not to.
    if args.offline:
        payload["verified"] = False
        payload["note"] = "offline: presence only; a present token may still be rejected by Apple"
    else:
        payload.update(_verify_tokens_live(developer_token, user_token))
    return _output_json(args, payload)


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
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )
