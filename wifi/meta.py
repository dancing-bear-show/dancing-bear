from __future__ import annotations

APP_ID = "wifi"
PURPOSE = "Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)"

AGENTIC_FALLBACK = f"agentic: {APP_ID}\npurpose: {PURPOSE}"
DOMAIN_MAP_FALLBACK = "Domain Map not available"
INVENTORY_FALLBACK = (
    "# LLM Agent Inventory (Wi-Fi)\n\n"
    "See repo .llm/INVENTORY.md for shared guidance.\n"
)
FAMILIAR_COMPACT_FALLBACK = (
    "meta:\n"
    "  name: wifi_familiarize\n"
    "  version: 1\n"
    "steps:\n"
    "  - run: ./bin/wifi --help\n"
)
FAMILIAR_EXTENDED_FALLBACK = (
    "meta:\n"
    "  name: wifi_familiarize\n"
    "  version: 1\n"
    "steps:\n"
    "  - run: ./bin/wifi diagnose --json\n"
)
POLICIES_FALLBACK = (
    "policies:\n"
    "  style:\n"
    "    - Keep CLI stable; prefer dry-run flows\n"
    "  tests:\n"
    "    - Add lightweight unittest for new CLI surfaces\n"
)
