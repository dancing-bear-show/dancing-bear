"""Agentic capsule for the Apple Music Assistant CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the LLM-readable agentic capsule text for apple-music-assistant."""
    lines: list[str] = []
    lines.append("agentic: apple-music-assistant")
    lines.append("purpose: Apple Music playlist management via the MusicKit API")
    lines.append("commands:")
    lines.append("  - verify tokens:         ./bin/apple-music-assistant ping")
    lines.append("  - list playlists:        ./bin/apple-music-assistant list --pretty")
    lines.append("  - list tracks:           ./bin/apple-music-assistant tracks --pretty")
    lines.append("  - export playlists:      ./bin/apple-music-assistant export --out playlists.json")
    lines.append("  - create playlist:       ./bin/apple-music-assistant create --preset spanish --count 20")
    lines.append("  - find duplicate playlists: ./bin/apple-music-assistant dedupe --pretty")
    lines.append("  - delete duplicates:     ./bin/apple-music-assistant dedupe --delete --keep latest")
    lines.append("  - mint developer token:  ./bin/apple-music-assistant token mint --save")
    lines.append("  - check token status:    ./bin/apple-music-assistant token status")
    lines.append("notes:")
    lines.append("  - credentials stored in ~/.config/credentials.ini under [apple_music.<profile>]")
    lines.append("  - developer token requires a MusicKit .p8 key (key_path, team_id, key_id)")
    lines.append("  - user token obtained via: bin/apple-music-user-token --serve --save")
    lines.append("  - most commands accept --out <file> to write JSON and --pretty for indented output")
    lines.append("  - token mint --save writes the developer token back to credentials.ini")
    lines.append("  - dedupe without --delete runs in plan-only mode (safe by default)")
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
