from __future__ import annotations

from core.meta_base import AppMeta

_META = AppMeta(
    app_id="qlty",
    purpose="Merged qlty check+smells scanning with per-rule triage strategy",
    display_name="Qlty",
    # Never ./bin/qlty -- that would shadow the real qlty binary on PATH.
    bin_name="./bin/qlty-assistant",
    example_cmd="./bin/qlty-assistant scan --format json",
)

# Re-export for backward compatibility
APP_ID = _META.app_id
PURPOSE = _META.purpose
AGENTIC_FALLBACK = _META.agentic_fallback
DOMAIN_MAP_FALLBACK = _META.domain_map_fallback
INVENTORY_FALLBACK = _META.inventory_fallback
FAMILIAR_COMPACT_FALLBACK = _META.familiar_compact_fallback
FAMILIAR_EXTENDED_FALLBACK = _META.familiar_extended_fallback
POLICIES_FALLBACK = _META.policies_fallback
