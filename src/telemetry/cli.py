"""telemetry CLI entry point — thin shim.

All implementations live in:
  - telemetry/cli_formatters.py  — pure formatting/data helpers
  - telemetry/cli_sessions.py    — CLIApp command group and subcommands

This shim re-exports the full public surface so that existing imports of
the form ``from telemetry.cli import <symbol>`` continue to work unchanged.
``bin/telemetry`` imports ``main`` from here, which delegates to cli_sessions.
"""
from __future__ import annotations

# Keep Path in this module's namespace so tests can patch 'telemetry.cli.Path.home'
# (the rules command in cli_sessions uses Path.home() — the test patches it here
# because the original code lived here; re-importing keeps the patch target valid).
from pathlib import Path  # noqa: F401

# Re-export main and internal helpers for backwards compat
from telemetry.cli_sessions import (  # noqa: F401
    _rules_explain,
    _rules_init,
    _rules_list,
    _rules_validate,
    main,
)

# Re-export all formatting/data helpers
from telemetry.cli_formatters import (  # noqa: F401
    _AGENT_SORT_KEYS,
    _agent_row_to_dict,
    _breakdown_by_agent,
    _breakdown_by_day,
    _build_agents_table,
    _build_breakdown_table,
    _build_sessions_table,
    _fmt_duration,
    _fmt_tokens,
    _parse_since_cli,
    _print_agents_csv,
    _print_agents_json,
    _print_cost_csv,
    _session_to_dict,
    _sessions_json_payload,
    _truncate_id,
)

if __name__ == "__main__":  # pragma: no cover
    main()
