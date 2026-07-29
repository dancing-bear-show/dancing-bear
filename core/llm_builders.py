"""Builder factories for domain-specific LLM modules.

Provides DomainLlmConfig and all _build_*_builder helpers used to construct
LlmConfig instances with minimal per-domain boilerplate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from core.llm_cli import LlmConfig

from core.textio import read_text as _read_text

# Fallback messages
_DOMAIN_MAP_UNAVAILABLE = "Domain Map not available"
_DEFAULT_POLICIES_YAML = (
    "policies:\n"
    "  style:\n"
    "    - Keep CLI stable; prefer plan→apply\n"
    "  tests:\n"
    "    - Add lightweight unittest for new CLI surfaces\n"
)

# Default filenames
DEFAULT_AGENTIC_FILENAME = "AGENTIC.md"
DEFAULT_DOMAIN_MAP_FILENAME = "DOMAIN_MAP.md"
DEFAULT_INVENTORY_FILENAME = "INVENTORY.md"
DEFAULT_FAMILIAR_FILENAME = "familiarize.yaml"
DEFAULT_POLICIES_FILENAME = "PR_POLICIES.yaml"


def _build_agentic_builder(agentic_module: str, app_id: str, purpose: str) -> Callable[[], str]:
    """Create agentic capsule builder for a domain module."""
    import importlib

    def builder() -> str:
        try:
            mod = importlib.import_module(agentic_module)
            return mod.build_agentic_capsule()
        except Exception:  # nosec B110 - fallback on import/build failure
            return f"agentic: {app_id}\npurpose: {purpose}"
    return builder


def _build_domain_map_builder(agentic_module: str) -> Callable[[], str]:
    """Create domain map builder for a domain module."""
    import importlib

    def builder() -> str:
        try:
            mod = importlib.import_module(agentic_module)
            return mod.build_domain_map()
        except Exception:  # nosec B110 - fallback on import/build failure
            return _DOMAIN_MAP_UNAVAILABLE
    return builder


def _build_inventory_builder(app_title: str) -> Callable[[], str]:
    """Create inventory builder for a domain module."""
    llm_dir = Path(".llm")

    def builder() -> str:
        return (
            _read_text(llm_dir / "INVENTORY.md")
            or f"# LLM Agent Inventory ({app_title})\n\nSee repo .llm/INVENTORY.md for shared guidance.\n"
        )
    return builder


def _build_familiar_compact_builder(
    app_id: str, familiar_compact_steps: list[str] | None
) -> Callable[[], str]:
    """Create compact familiarization builder for a domain module."""
    llm_dir = Path(".llm")

    def builder() -> str:
        if familiar_compact_steps:
            steps = "\n".join(f"  - run: {cmd}" for cmd in familiar_compact_steps)
            return (
                f"meta:\n"
                f"  name: {app_id}_familiarize\n"
                f"  version: 1\n"
                f"steps:\n{steps}\n"
            )
        return (
            _read_text(llm_dir / "familiarize.yaml")
            or f"meta:\n  name: {app_id}_familiarize\n  version: 1\nsteps:\n  - run: ./bin/{app_id} --help\n"
        )
    return builder


def _build_familiar_extended_builder(
    app_id: str,
    familiar_extended_steps: list[str] | None,
    compact_builder: Callable[[], str],
) -> Callable[[], str]:
    """Create extended familiarization builder for a domain module."""
    def builder() -> str:
        if familiar_extended_steps:
            steps = "\n".join(f"  - run: {cmd}" for cmd in familiar_extended_steps)
            return (
                f"meta:\n"
                f"  name: {app_id}_familiarize\n"
                f"  version: 1\n"
                f"steps:\n{steps}\n"
            )
        return compact_builder()
    return builder


def _build_policies_builder(policies_fallback: str | None) -> Callable[[], str]:
    """Create policies builder for a domain module."""
    llm_dir = Path(".llm")

    def builder() -> str:
        return (
            _read_text(llm_dir / "PR_POLICIES.yaml")
            or policies_fallback
            or _DEFAULT_POLICIES_YAML
        )
    return builder


@dataclass(frozen=True)
class DomainLlmConfig:
    """Configuration for creating domain-specific LLM modules.

    Groups identity fields (app_id, app_title, purpose, agentic_module)
    with optional customization (familiar steps, policies fallback).
    """

    app_id: str
    app_title: str
    purpose: str
    agentic_module: str
    familiar_compact_steps: list[str] | None = None
    familiar_extended_steps: list[str] | None = None
    policies_fallback: str | None = None


def make_domain_llm_module(
    config: DomainLlmConfig | None = None,
    **kwargs: Any,
) -> "LlmConfig":
    """Factory to create an LlmConfig for a domain module with minimal boilerplate.

    Args:
        config: DomainLlmConfig with all domain settings.
                For convenience, keyword arguments are also accepted
                and forwarded to DomainLlmConfig().

    Returns:
        LlmConfig ready for use with build_parser() and run()
    """
    # Import here to avoid circular imports — llm_cli imports from llm_builders
    from core.llm_cli import LlmConfig

    if config is None:
        config = DomainLlmConfig(**kwargs)

    agentic_builder = _build_agentic_builder(config.agentic_module, config.app_id, config.purpose)
    domain_map_builder = _build_domain_map_builder(config.agentic_module)
    inventory_builder = _build_inventory_builder(config.app_title)
    compact_builder = _build_familiar_compact_builder(config.app_id, config.familiar_compact_steps)
    extended_builder = _build_familiar_extended_builder(
        config.app_id, config.familiar_extended_steps, compact_builder
    )
    policies_builder = _build_policies_builder(config.policies_fallback)

    return LlmConfig(
        prog=f"llm-{config.app_id}",
        description=(
            f"{config.app_title} Assistant LLM utilities"
            " (inventory, familiar, policies, agentic, domain-map)"
        ),
        agentic=agentic_builder,
        domain_map=domain_map_builder,
        inventory=inventory_builder,
        familiar_compact=compact_builder,
        familiar_extended=extended_builder,
        policies=policies_builder,
        agentic_filename=f"AGENTIC_{config.app_id.upper()}.md",
        domain_map_filename=f"DOMAIN_MAP_{config.app_id.upper()}.md",
    )
