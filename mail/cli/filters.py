"""Filters CLI registration.

Centralizes wiring for the `filters` group to match the existing CLI
shape exactly.
"""
from __future__ import annotations


def register(subparsers, **handlers):
    """Register filters subcommands.

    Args:
        subparsers: Argument subparsers to register commands with
        **handlers: Command handler functions (f_list, f_export, etc.)

    Raises:
        ValueError: If any required handler is missing
    """
    required_keys = [
        "f_list", "f_export", "f_sync", "f_plan", "f_impact", "f_sweep",
        "f_sweep_range", "f_delete", "f_prune_empty", "f_add_forward_by_label",
        "f_add_from_token", "f_rm_from_token"
    ]
    missing = [k for k in required_keys if k not in handlers]
    if missing:
        raise ValueError(f"Missing required handlers: {missing}")

    f_list = handlers["f_list"]
    f_export = handlers["f_export"]
    f_sync = handlers["f_sync"]
    f_plan = handlers["f_plan"]
    f_impact = handlers["f_impact"]
    f_sweep = handlers["f_sweep"]
    f_sweep_range = handlers["f_sweep_range"]
    f_delete = handlers["f_delete"]
    f_prune_empty = handlers["f_prune_empty"]
    f_add_forward_by_label = handlers["f_add_forward_by_label"]
    f_add_from_token = handlers["f_add_from_token"]
    f_rm_from_token = handlers["f_rm_from_token"]
    p_filters = subparsers.add_parser("filters", help="Message filter operations (including forwarding)")
    # Group-level common Gmail args
    p_filters.add_argument("--credentials", type=str)
    p_filters.add_argument("--token", type=str)
    p_filters.add_argument("--cache", type=str, help="Cache directory (optional)")
    sub_filters = p_filters.add_subparsers(dest="filters_cmd")

    # list
    p_filters_list = sub_filters.add_parser("list", help="List existing Gmail filters")
    p_filters_list.set_defaults(func=f_list)

    # export
    p_filters_export = sub_filters.add_parser("export", help="Export filters to YAML")
    p_filters_export.add_argument("--out", required=True)
    p_filters_export.set_defaults(func=f_export)

    # sync
    p_filters_sync = sub_filters.add_parser("sync", help="Sync filters from YAML (supports forwarding)")
    p_filters_sync.add_argument("--config", required=True)
    p_filters_sync.add_argument("--dry-run", action="store_true")
    p_filters_sync.add_argument(
        "--delete-missing", action="store_true", help="Delete filters not present in config"
    )
    p_filters_sync.add_argument(
        "--require-forward-verified", action="store_true", help="Fail if forward address not verified"
    )
    p_filters_sync.set_defaults(func=f_sync)

    # plan
    p_filters_plan = sub_filters.add_parser(
        "plan", help="Plan changes from YAML against current filters (human-readable)"
    )
    p_filters_plan.add_argument("--config", required=True)
    p_filters_plan.add_argument(
        "--delete-missing", action="store_true", help="Show filters that would be deleted (not present in YAML)"
    )
    p_filters_plan.set_defaults(func=f_plan)

    # impact (counts)
    p_filters_impact = sub_filters.add_parser(
        "impact", help="Estimate impact (message counts) per filter from YAML"
    )
    p_filters_impact.add_argument("--config", required=True)
    p_filters_impact.add_argument("--days", type=int)
    p_filters_impact.add_argument("--only-inbox", action="store_true")
    p_filters_impact.add_argument("--pages", type=int, default=5)
    p_filters_impact.set_defaults(func=f_impact)

    # sweep (apply actions to existing mail)
    p_filters_sweep = sub_filters.add_parser(
        "sweep", help="Apply YAML filter actions to existing messages"
    )
    p_filters_sweep.add_argument("--config", required=True)
    p_filters_sweep.add_argument("--days", type=int)
    p_filters_sweep.add_argument("--only-inbox", action="store_true")
    p_filters_sweep.add_argument("--pages", type=int, default=50)
    p_filters_sweep.add_argument("--batch-size", type=int, default=500)
    p_filters_sweep.add_argument("--max-msgs", type=int)
    p_filters_sweep.add_argument("--dry-run", action="store_true")
    p_filters_sweep.set_defaults(func=f_sweep)

    # sweep-range (progressive windows)
    p_filters_sweep_range = sub_filters.add_parser(
        "sweep-range", help="Sweep in time windows back to oldest mail"
    )
    p_filters_sweep_range.add_argument("--config", required=True)
    p_filters_sweep_range.add_argument(
        "--from-days", type=int, default=0, help="Start at N days ago (default 0)"
    )
    p_filters_sweep_range.add_argument(
        "--to-days", type=int, required=True, help="End at N days ago (e.g., 3650)"
    )
    p_filters_sweep_range.add_argument(
        "--step-days", type=int, default=90, help="Window size in days (default 90)"
    )
    p_filters_sweep_range.add_argument("--pages", type=int, default=100)
    p_filters_sweep_range.add_argument("--batch-size", type=int, default=500)
    p_filters_sweep_range.add_argument("--max-msgs", type=int)
    p_filters_sweep_range.add_argument("--dry-run", action="store_true")
    p_filters_sweep_range.set_defaults(func=f_sweep_range)

    # delete by ID (advanced)
    p_filters_delete = sub_filters.add_parser(
        "delete", help="Delete a Gmail filter by ID (advanced)"
    )
    p_filters_delete.add_argument("--id", required=True)
    p_filters_delete.set_defaults(func=f_delete)

    # prune-empty
    p_filters_prune = sub_filters.add_parser(
        "prune-empty", help="Delete filters that match no messages (by sampling)"
    )
    p_filters_prune.add_argument("--days", type=int, default=7, help="Restrict query to last N days")
    p_filters_prune.add_argument(
        "--only-inbox", action="store_true", help="Restrict to inbox for estimation"
    )
    p_filters_prune.add_argument("--pages", type=int, default=2, help="Pages to sample for impact estimation")
    p_filters_prune.add_argument("--dry-run", action="store_true")
    p_filters_prune.set_defaults(func=f_prune_empty)

    # add-forward-by-label
    p_filters_addf = sub_filters.add_parser(
        "add-forward-by-label",
        help="Add forward action to all filters that add a given label prefix (e.g., 'Kids' forwards includes 'Kids/*')",
    )
    p_filters_addf.add_argument(
        "--label-prefix", required=True, help="Label name/prefix to match (e.g., Kids)"
    )
    p_filters_addf.add_argument(
        "--email", required=True, help="Forward destination email (must be verified)"
    )
    p_filters_addf.add_argument("--dry-run", action="store_true")
    p_filters_addf.add_argument(
        "--require-forward-verified", action="store_true", help="Fail if forward address not verified"
    )
    p_filters_addf.set_defaults(func=f_add_forward_by_label)

    # add-from-token
    p_filters_addfrom = sub_filters.add_parser(
        "add-from-token",
        help="Add a token to 'from' criteria of filters matching a label prefix and needle",
    )
    p_filters_addfrom.add_argument(
        "--label-prefix", required=True, help="Label name/prefix to match (e.g., Kids)"
    )
    p_filters_addfrom.add_argument(
        "--needle", required=True, help="Substring to find in existing from criteria (case-insensitive)"
    )
    p_filters_addfrom.add_argument(
        "--add", action="append", required=True, help="Token(s) to add to OR list in from criteria (repeatable)"
    )
    p_filters_addfrom.add_argument("--dry-run", action="store_true")
    p_filters_addfrom.set_defaults(func=f_add_from_token)

    # rm-from-token
    p_filters_rmfrom = sub_filters.add_parser(
        "rm-from-token",
        help="Remove token(s) from 'from' criteria OR-list for filters matching a label prefix and needle",
    )
    p_filters_rmfrom.add_argument(
        "--label-prefix", required=True, help="Label name/prefix to match (e.g., Kids)"
    )
    p_filters_rmfrom.add_argument(
        "--needle", required=True, help="Substring to find in existing from criteria (case-insensitive)"
    )
    p_filters_rmfrom.add_argument(
        "--remove", action="append", required=True, help="Token(s) to remove from OR list in from criteria (repeatable)"
    )
    p_filters_rmfrom.add_argument("--dry-run", action="store_true")
    p_filters_rmfrom.set_defaults(func=f_rm_from_token)
