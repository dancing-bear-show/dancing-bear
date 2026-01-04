from __future__ import annotations

def register(subparsers, **handlers):
    """Register accounts subcommands.

    Args:
        subparsers: Argument subparsers to register commands with
        **handlers: Command handler functions (f_list, f_export_labels, etc.)

    Raises:
        ValueError: If any required handler is missing
    """
    required_keys = [
        "f_list", "f_export_labels", "f_sync_labels", "f_export_filters",
        "f_sync_filters", "f_plan_labels", "f_plan_filters",
        "f_export_signatures", "f_sync_signatures"
    ]
    missing = [k for k in required_keys if k not in handlers]
    if missing:
        raise ValueError(f"Missing required handlers: {missing}")

    f_list = handlers["f_list"]
    f_export_labels = handlers["f_export_labels"]
    f_sync_labels = handlers["f_sync_labels"]
    f_export_filters = handlers["f_export_filters"]
    f_sync_filters = handlers["f_sync_filters"]
    f_plan_labels = handlers["f_plan_labels"]
    f_plan_filters = handlers["f_plan_filters"]
    f_export_signatures = handlers["f_export_signatures"]
    f_sync_signatures = handlers["f_sync_signatures"]
    p_accts = subparsers.add_parser("accounts", help="Operate across multiple email accounts/providers")
    sub_accts = p_accts.add_subparsers(dest="accounts_cmd")

    def _add(name, func, extra_args=()):
        sp = sub_accts.add_parser(name, help=f"{name.replace('-', ' ').title()} across selected accounts")
        sp.add_argument("--config", required=True, help="Accounts YAML with provider/credentials")
        sp.add_argument("--accounts", help="Comma-separated list of account names to include; default all")
        sp.add_argument("--dry-run", action="store_true")
        for arg_name, kwargs in extra_args:
            sp.add_argument(arg_name, **kwargs)
        sp.set_defaults(func=func)

    _add("list", f_list)
    _add("export-labels", f_export_labels, [("--out-dir", {"required": True})])
    _add("sync-labels", f_sync_labels, [("--labels", {"required": True})])
    _add("export-filters", f_export_filters, [("--out-dir", {"required": True})])
    _add(
        "sync-filters",
        f_sync_filters,
        [("--filters", {"required": True}), ("--require-forward-verified", {"action": "store_true"})],
    )
    _add("plan-labels", f_plan_labels, [("--labels", {"required": True})])
    _add("plan-filters", f_plan_filters, [("--filters", {"required": True})])
    _add("export-signatures", f_export_signatures, [("--out-dir", {"required": True})])
    _add("sync-signatures", f_sync_signatures, [("--send-as", {})])

