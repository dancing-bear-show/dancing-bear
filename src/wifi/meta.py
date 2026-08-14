from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="wifi",
    purpose="Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)",
    display_name="Wi-Fi",
    example_cmd="./bin/wifi diagnose --json",
)
