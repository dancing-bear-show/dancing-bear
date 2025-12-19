"""CLI to export Apple Music library playlists."""

from __future__ import annotations

from apple_music_assistant.cli import (
    AppleMusicCLI,
    CreateCommand,
    ExportCommand,
    ListCommand,
    PingCommand,
    DedupeCommand,
    TracksCommand,
)


def main(argv: list[str] | None = None) -> int:
    cli = AppleMusicCLI(commands=[ExportCommand(), ListCommand(), TracksCommand(), PingCommand(), CreateCommand(), DedupeCommand()])
    return cli.run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
