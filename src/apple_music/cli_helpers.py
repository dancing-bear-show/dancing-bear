"""Shared auth, client, and output helpers for the Apple Music CLI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.cli_output import OutputConfig, OutputFormat, OutputWriter

from .config import DEFAULT_PROFILE, load_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
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


def _format_timestamp(epoch: int | None) -> str | None:
    """Render a unix timestamp as a UTC ISO-8601 string, or None when absent."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def save_credential_value(config_path: Path, profile: str, key: str, value: str) -> None:
    """Set ``key = value`` under ``profile`` in credentials.ini, preserving other content.

    Writes via a private temp file in the same directory and an atomic replace, so a
    failure mid-write cannot truncate the credentials file.
    """
    import configparser  # noqa: PLC0415 - stdlib, only needed on the save path

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path)
    if not parser.has_section(profile):
        parser.add_section(profile)
    parser.set(profile, key, value)

    original_mode = config_path.stat().st_mode & 0o777
    fd, tmp_name = tempfile.mkstemp(dir=str(config_path.parent), prefix=".credentials-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, original_mode)
        with os.fdopen(fd, "w") as handle:
            parser.write(handle)
        os.replace(tmp_path, config_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _output_json(args: Any, payload: dict[str, Any]) -> int:
    """Output JSON payload to stdout or file via OutputWriter."""
    pretty = getattr(args, "pretty", False)
    out_path = getattr(args, "out", None)
    json_text = json.dumps(payload, indent=2 if pretty else None)
    if out_path:
        Path(out_path).write_text(json_text)
    else:
        writer = OutputWriter(OutputConfig(format=OutputFormat.TEXT))
        writer.print(json_text)
    return 0
