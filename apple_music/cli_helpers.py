"""Shared auth, client, and output helpers for the Apple Music CLI."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .client import AppleMusicClient
from .config import DEFAULT_PROFILE, load_profile


@dataclass
class PlaylistCreationConfig:
    """Configuration for creating a playlist from seed tracks."""

    name: str
    description: str | None = None
    count: int = 20
    shuffle_seed: int | None = None
    storefront: str | None = None
    dry_run: bool = False


def _resolve_tokens(args) -> tuple[str | None, str | None]:
    """Resolve developer and user tokens from args, env, or config."""
    profile = getattr(args, "profile", None) or DEFAULT_PROFILE
    config_path = getattr(args, "config", None)
    _, profile_cfg = load_profile(profile, config_path)
    developer_token = (
        getattr(args, "developer_token", None)
        or os.environ.get("APPLE_MUSIC_DEVELOPER_TOKEN")
        or profile_cfg.get("developer_token")
    )
    user_token = (
        getattr(args, "user_token", None)
        or os.environ.get("APPLE_MUSIC_USER_TOKEN")
        or profile_cfg.get("user_token")
    )
    return developer_token, user_token


def _get_client(args) -> AppleMusicClient:
    """Create an AppleMusicClient from args."""
    developer_token, user_token = _resolve_tokens(args)
    if not developer_token:
        print("Missing developer token. Provide --developer-token or set developer_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    if not user_token:
        print("Missing user token. Provide --user-token or set user_token in credentials.ini.", file=sys.stderr)
        raise SystemExit(2)
    return AppleMusicClient(developer_token, user_token)


def _output_json(args, payload: dict) -> int:
    """Output JSON payload to stdout or file."""
    pretty = getattr(args, "pretty", False)
    out_path = getattr(args, "out", None)
    json_text = json.dumps(payload, indent=2 if pretty else None)
    if out_path:
        Path(out_path).write_text(json_text)
    else:
        print(json_text)
    return 0
