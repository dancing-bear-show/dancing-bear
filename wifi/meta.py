from __future__ import annotations

from core.meta_base import AppMeta

_META = AppMeta(
    app_id="wifi",
    purpose="Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)",
    display_name="Wi-Fi",
    example_cmd="./bin/wifi diagnose --json",
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
