"""Repo-level LLM CLI: agentic/domain-map/familiar content and command dispatch.

Thin re-export shim. Implementation lives in:
  - core.llm_handlers  — CLI handler functions and main entry point
  - core.llm_staleness — stale/deps/check analytics
"""

from __future__ import annotations

from core.llm_handlers import (  # noqa: F401
    ASSISTANT_AGENTIC_CORE_CMDS,
    ASSISTANT_AGENTIC_EXTENDED_CMDS,
    ASSISTANT_VIZ_ORCHESTRATION_CMDS,
    _APP_MODULES,
    _build_repo_parser,
    _default_inventory,
    _default_policies,
    _emit_content,
    _extract_app_arg,
    _familiar_content,
    _handle_agentic,
    _handle_derive_all,
    _handle_domain_map,
    _handle_familiar,
    _handle_flows,
    _handle_inventory,
    _handle_policies,
    _mail_agentic_capsule,
    _mail_domain_map,
    _mail_flows,
    _render_flow_content,
    _run_app_cli,
    main,
)

from core.llm_staleness import (  # noqa: F401
    DEFAULT_SKIP_DIRS,
    DEFAULT_SLA_DAYS,
    _aggregate_values,
    _collect_dep_stats,
    _collect_excludes,
    _collect_stale_stats,
    _fail_on_stale,
    _handle_check,
    _handle_deps,
    _handle_stale,
    _iter_candidate_dirs,
    _latest_mtime,
    _parse_sla_env,
    _split_list,
    _stale_md_row,
    _stale_text_line,
    _status_for_area,
)
