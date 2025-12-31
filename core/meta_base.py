"""Base module for app metadata with fallback strings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AppMeta:
    """App metadata with LLM fallback strings."""

    app_id: str
    purpose: str
    display_name: Optional[str] = None  # human-readable name (defaults to title-cased app_id)
    bin_name: Optional[str] = None  # defaults to ./bin/{app_id}
    help_cmd: Optional[str] = None  # default help command
    example_cmd: Optional[str] = None  # example command for extended familiarization

    @property
    def _display_name(self) -> str:
        """Get display name, defaulting to title-cased app_id."""
        return self.display_name or self.app_id.replace("_", " ").title()

    @property
    def agentic_fallback(self) -> str:
        return f"agentic: {self.app_id}\npurpose: {self.purpose}"

    @property
    def domain_map_fallback(self) -> str:
        return "Domain Map not available"

    @property
    def inventory_fallback(self) -> str:
        return (
            f"# LLM Agent Inventory ({self._display_name})\n\n"
            "See repo .llm/INVENTORY.md for shared guidance.\n"
        )

    @property
    def familiar_compact_fallback(self) -> str:
        bin_name = self.bin_name or f"./bin/{self.app_id}"
        help_cmd = self.help_cmd or f"{bin_name} --help"
        return (
            "meta:\n"
            f"  name: {self.app_id}_familiarize\n"
            "  version: 1\n"
            "steps:\n"
            f"  - run: {help_cmd}\n"
        )

    @property
    def familiar_extended_fallback(self) -> str:
        bin_name = self.bin_name or f"./bin/{self.app_id}"
        example = self.example_cmd or f"{bin_name} --help"
        return (
            "meta:\n"
            f"  name: {self.app_id}_familiarize\n"
            "  version: 1\n"
            "steps:\n"
            f"  - run: {example}\n"
        )

    @property
    def policies_fallback(self) -> str:
        return (
            "policies:\n"
            "  style:\n"
            "    - Keep CLI stable; prefer dry-run flows\n"
            "  tests:\n"
            "    - Add lightweight unittest for new CLI surfaces\n"
        )
