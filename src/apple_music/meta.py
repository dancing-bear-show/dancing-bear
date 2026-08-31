from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="apple-music-assistant",
    purpose="Apple Music playlist management via the MusicKit API",
    display_name="Apple Music",
    bin_name="./bin/apple-music-assistant",
    example_cmd="./bin/apple-music-assistant list --pretty",
)
