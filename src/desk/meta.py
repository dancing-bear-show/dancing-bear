from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="desk",
    purpose="Scan, plan, and tidy macOS folders",
    display_name="Desk",
    example_cmd="./bin/desk scan --paths ~/Downloads --duplicates",
)
