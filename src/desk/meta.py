from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="desk",
    purpose="Scan, plan, and tidy macOS folders",
    display_name="Desk",
    bin_name="python3 -m desk",
    example_cmd="python3 -m desk scan --json",
)
