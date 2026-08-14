from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="qlty",
    purpose="Merged qlty check+smells scanning with per-rule triage strategy",
    display_name="Qlty",
    # Never ./bin/qlty -- that would shadow the real qlty binary on PATH.
    bin_name="./bin/qlty-assistant",
    example_cmd="./bin/qlty-assistant scan --format json",
)
