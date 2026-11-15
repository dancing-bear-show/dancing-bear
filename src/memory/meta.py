from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="memory",
    purpose="Claude auto-memory: list, show, search, validate, consolidate, export/import, backup",
    display_name="Memory",
    bin_name="./bin/memory",
    example_cmd="./bin/memory validate --format table",
)
