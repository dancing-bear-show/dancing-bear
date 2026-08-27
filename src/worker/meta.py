"""App metadata for the worker CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="worker",
    purpose="Background worker queue and daemon for job processing",
    display_name="Worker",
    example_cmd="./bin/worker list",
)
