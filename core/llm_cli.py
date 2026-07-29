"""Shared LLM CLI helpers — thin shim over core.llm_builders and core.llm_domain."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, Sequence

# ---------------------------------------------------------------------------
# Re-exports from core.llm_builders
# (llm_builders imports LlmConfig from here lazily, so no circular import)
# ---------------------------------------------------------------------------
from core.llm_builders import (  # noqa: F401
    DEFAULT_AGENTIC_FILENAME,
    DEFAULT_DOMAIN_MAP_FILENAME,
    DEFAULT_FAMILIAR_FILENAME,
    DEFAULT_INVENTORY_FILENAME,
    DEFAULT_POLICIES_FILENAME,
    DomainLlmConfig,
    _build_agentic_builder,
    _build_domain_map_builder,
    _build_familiar_compact_builder,
    _build_familiar_extended_builder,
    _build_inventory_builder,
    _build_policies_builder,
    make_domain_llm_module,
)

# ---------------------------------------------------------------------------
# Re-exports from core.llm_domain
# (llm_domain imports run from here lazily, so no circular import)
# ---------------------------------------------------------------------------
from core.llm_domain import (  # noqa: F401
    ASSISTANT_AGENTIC_CORE_CMDS,
    ASSISTANT_AGENTIC_EXTENDED_CMDS,
    ASSISTANT_VIZ_ORCHESTRATION_CMDS,
    DEFAULT_SLA_DAYS,
    DEFAULT_SKIP_DIRS,
    _APP_MODULES,
    _build_repo_parser,
    _collect_dep_stats,
    _collect_excludes,
    _collect_stale_stats,
    _default_inventory,
    _default_policies,
    _emit_content,
    _extract_app_arg,
    _fail_on_stale,
    _familiar_content,
    _handle_agentic,
    _handle_check,
    _handle_deps,
    _handle_derive_all,
    _handle_domain_map,
    _handle_familiar,
    _handle_flows,
    _handle_inventory,
    _handle_policies,
    _handle_stale,
    _iter_candidate_dirs,
    _latest_mtime,
    _mail_agentic_capsule,
    _mail_domain_map,
    _mail_flows,
    _parse_sla_env,
    _render_flow_content,
    _run_app_cli,
    _split_list,
    _stale_md_row,
    _stale_text_line,
    _status_for_area,
    main,
)

# ---------------------------------------------------------------------------
# Locals (LlmConfig must be defined here — llm_builders back-imports it)
# ---------------------------------------------------------------------------

_DOMAIN_MAP_UNAVAILABLE = "Domain Map not available"
_DEFAULT_POLICIES_YAML = (
    "policies:\n"
    "  style:\n"
    "    - Keep CLI stable; prefer plan→apply\n"
    "  tests:\n"
    "    - Add lightweight unittest for new CLI surfaces\n"
)


@dataclass
class LlmConfig:
    prog: str
    description: str
    agentic: Callable[[], str]
    domain_map: Callable[[], str] | None = None
    inventory: Callable[[], str] | None = None
    familiar_compact: Callable[[], str] | None = None
    familiar_extended: Callable[[], str] | None = None
    policies: Callable[[], str] | None = None
    agentic_filename: str = DEFAULT_AGENTIC_FILENAME
    domain_map_filename: str = DEFAULT_DOMAIN_MAP_FILENAME
    inventory_filename: str = DEFAULT_INVENTORY_FILENAME
    familiar_filename: str = DEFAULT_FAMILIAR_FILENAME
    policies_filename: str = DEFAULT_POLICIES_FILENAME


def make_app_llm_config(**kwargs) -> LlmConfig:
    """Create LlmConfig instance.

    This is a convenience wrapper around LlmConfig constructor.
    For new code, prefer using LlmConfig(...) directly.

    Args:
        **kwargs: Arguments passed to LlmConfig constructor.
                  Required: prog, description, agentic
                  Optional: domain_map, inventory, familiar_compact, familiar_extended,
                           policies, agentic_filename, domain_map_filename,
                           inventory_filename, familiar_filename, policies_filename

    Returns:
        LlmConfig instance.
    """
    return LlmConfig(**kwargs)


# ---------------------------------------------------------------------------
# App-level helpers (used by per-domain LLM modules via their own llm_cli.py)
# ---------------------------------------------------------------------------


def _safe_call(builder: Callable[[], str] | None, fallback: str) -> str:
    if builder is None:
        return fallback
    try:
        text = builder()
    except Exception as exc:  # nosec B110 - surface fallback instead of crashing
        return fallback or f"(error generating content: {exc})"
    return text or fallback


def _make_emit_command_handler(
    builder: Callable[[], str] | None, fallback: str
) -> Callable:
    """Create a handler function for emit commands (agentic, domain-map, etc.)."""

    def _run(args):
        content = _safe_call(builder, fallback)
        _emit_content(content, getattr(args, "write", None), getattr(args, "stdout", False))
        return 0

    return _run


def _make_familiar_handler(config: LlmConfig) -> Callable:
    """Create handler for the familiar command."""

    def _run_familiar(args):
        verbose = bool(getattr(args, "verbose", False))
        builder = (
            config.familiar_extended
            if verbose and config.familiar_extended
            else config.familiar_compact
        )
        fallback = (
            "meta:\n  name: familiar\n  version: 1\n"
            "steps:\n  - run: ./bin/llm agentic --stdout\n"
        )
        content = _safe_call(builder, fallback)
        _emit_content(content, getattr(args, "write", None), getattr(args, "stdout", False))
        return 0

    return _run_familiar


def _collect_derive_outputs(config: LlmConfig) -> list[tuple[str, str]]:
    """Collect (filename, content) pairs from config builders."""
    outputs: list[tuple[str, str]] = []

    def _add(
        filename: str | None,
        builder: Callable[[], str] | None,
        fallback: str = "",
    ) -> None:
        if not filename or not builder:
            return
        content = _safe_call(builder, fallback)
        if content:
            outputs.append((filename, content))

    _add(config.agentic_filename, config.agentic)
    _add(config.domain_map_filename, config.domain_map)
    _add(config.inventory_filename, config.inventory)
    fam_builder = config.familiar_extended or config.familiar_compact
    _add(config.familiar_filename, fam_builder)
    _add(config.policies_filename, config.policies, _default_policies())

    if hasattr(config, "extra_generators"):
        extra: Sequence[tuple[str, Callable[[], str]]] = getattr(config, "extra_generators")
        for fname, builder in extra:
            _add(fname, builder)

    return outputs


def _make_derive_handler(config: LlmConfig) -> Callable:
    """Create handler for the derive-all command."""
    from pathlib import Path

    def _run_derive(args):
        outputs = _collect_derive_outputs(config)

        if getattr(args, "include_generated", False) and outputs:
            out_dir = Path(getattr(args, "out_dir", ".llm") or ".llm")
            out_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in outputs:
                target = out_dir / fname
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        summary_lines = (
            ["Generated:"] + ([f"- {f}" for f, _ in outputs] if outputs else ["- (none)"])
        )
        if getattr(args, "stdout", False) or not getattr(args, "include_generated", False):
            print("\n".join(summary_lines))
        return 0

    return _run_derive


def _add_emit_subcommand(
    subparsers,
    name: str,
    help_text: str,
    builder: Callable[[], str] | None,
    fallback: str,
) -> None:
    """Add an emit-style subcommand to a parser."""
    cmd = subparsers.add_parser(name, help=help_text)
    cmd.add_argument("--write", help="Write output path")
    cmd.add_argument("--stdout", action="store_true", help="Print to stdout")
    cmd.set_defaults(func=_make_emit_command_handler(builder, fallback))


def _build_app_parser(config: LlmConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=config.prog, description=config.description)
    sub = parser.add_subparsers(dest="cmd", required=True)

    _add_emit_subcommand(
        sub, "agentic", "Emit the agentic capsule", config.agentic, "agentic: (not available)"
    )
    _add_emit_subcommand(
        sub, "domain-map", "Emit domain map", config.domain_map, _DOMAIN_MAP_UNAVAILABLE
    )
    _add_emit_subcommand(
        sub,
        "inventory",
        "Emit LLM inventory",
        config.inventory,
        "# LLM Agent Inventory\n\n(no data)",
    )
    _add_emit_subcommand(
        sub, "policies", "Emit PR/testing policies", config.policies, _default_policies()
    )

    fam = sub.add_parser("familiar", help="Emit familiarization capsule")
    fam.add_argument("--write", help="Write output path")
    fam.add_argument("--stdout", action="store_true", help="Print to stdout")
    fam.add_argument("--verbose", action="store_true", help="Include extended steps")
    fam.set_defaults(func=_make_familiar_handler(config))

    derive = sub.add_parser("derive-all", help="Generate agentic + domain map artifacts")
    derive.add_argument(
        "--out-dir", default=".llm", help="Directory for generated files (default .llm)"
    )
    derive.add_argument(
        "--include-generated", action="store_true", help="Write artifacts to --out-dir"
    )
    derive.add_argument("--stdout", action="store_true", help="Print summary to stdout")
    derive.set_defaults(func=_make_derive_handler(config))

    return parser


def build_parser(config: LlmConfig) -> argparse.ArgumentParser:
    return _build_app_parser(config)


def run(config: LlmConfig, argv: list[str] | None = None) -> int:
    parser = build_parser(config)
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args))
