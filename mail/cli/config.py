from __future__ import annotations


def register(subparsers, **handlers):
    """Register config subcommands.

    Args:
        subparsers: Argument subparsers to register commands with
        **handlers: Command handler functions (f_inspect, f_derive_labels, etc.)

    Raises:
        ValueError: If any required handler is missing
    """
    required_keys = ["f_inspect", "f_derive_labels", "f_derive_filters", "f_optimize_filters", "f_audit_filters"]
    missing = [k for k in required_keys if k not in handlers]
    if missing:
        raise ValueError(f"Missing required handlers: {missing}")

    f_inspect = handlers["f_inspect"]
    f_derive_labels = handlers["f_derive_labels"]
    f_derive_filters = handlers["f_derive_filters"]
    f_optimize_filters = handlers["f_optimize_filters"]
    f_audit_filters = handlers["f_audit_filters"]
    p_cfg = subparsers.add_parser("config", help="Inspect and manage configuration")
    sub_cfg = p_cfg.add_subparsers(dest="config_cmd")

    # config inspect
    p_cfg_inspect = sub_cfg.add_parser("inspect", help="Show config with redacted secrets")
    p_cfg_inspect.add_argument("--path", default="~/.config/credentials.ini", help="Path to INI file")
    p_cfg_inspect.add_argument("--section", help="Only show a specific section")
    p_cfg_inspect.add_argument("--only-mail", action="store_true", help="Restrict to mail.* sections")
    p_cfg_inspect.set_defaults(func=f_inspect)

    # config derive
    p_cfg_derive = sub_cfg.add_parser("derive", help="Derive provider-specific configs from a unified YAML")
    sub_cfg_derive = p_cfg_derive.add_subparsers(dest="derive_cmd")

    p_cfg_derive_labels = sub_cfg_derive.add_parser("labels", help="Derive Gmail and Outlook labels YAML from unified labels.yaml")
    p_cfg_derive_labels.add_argument("--in", dest="in_path", required=True, help="Unified labels YAML (labels: [])")
    p_cfg_derive_labels.add_argument("--out-gmail", required=True, help="Output Gmail labels YAML")
    p_cfg_derive_labels.add_argument("--out-outlook", required=True, help="Output Outlook categories YAML")
    p_cfg_derive_labels.set_defaults(func=f_derive_labels)

    p_cfg_derive_filters = sub_cfg_derive.add_parser("filters", help="Derive Gmail and Outlook filters YAML from unified filters.yaml")
    p_cfg_derive_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_derive_filters.add_argument("--out-gmail", required=True, help="Output Gmail filters YAML")
    p_cfg_derive_filters.add_argument("--out-outlook", required=True, help="Output Outlook rules YAML")
    p_cfg_derive_filters.set_defaults(outlook_move_to_folders=True)
    p_cfg_derive_filters.add_argument("--outlook-move-to-folders", action="store_true", dest="outlook_move_to_folders", help="Encode moveToFolder from first added label for Outlook (default on)")
    p_cfg_derive_filters.add_argument("--no-outlook-move-to-folders", action="store_false", dest="outlook_move_to_folders", help="Do not encode moveToFolder; categories-only on Outlook")
    p_cfg_derive_filters.add_argument(
        "--outlook-archive-on-remove-inbox",
        action="store_true",
        dest="outlook_archive_on_remove_inbox",
        help="When YAML removes INBOX, derive Outlook rules that move to Archive",
    )
    p_cfg_derive_filters.set_defaults(func=f_derive_filters)

    # config optimize
    p_cfg_opt = sub_cfg.add_parser("optimize", help="Optimize unified configs by merging similar rules")
    sub_cfg_opt = p_cfg_opt.add_subparsers(dest="optimize_cmd")
    p_cfg_opt_filters = sub_cfg_opt.add_parser("filters", help="Merge rules with same destination label and simple from criteria")
    p_cfg_opt_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_opt_filters.add_argument("--out", required=True, help="Output optimized unified filters YAML")
    p_cfg_opt_filters.add_argument("--merge-threshold", type=int, default=2, help="Minimum number of rules to merge (default 2)")
    p_cfg_opt_filters.add_argument("--preview", action="store_true", help="Print a summary of merges")
    p_cfg_opt_filters.set_defaults(func=f_optimize_filters)

    # config audit
    p_cfg_audit = sub_cfg.add_parser("audit", help="Audit unified coverage vs provider exports")
    sub_cfg_audit = p_cfg_audit.add_subparsers(dest="audit_cmd")
    p_cfg_audit_filters = sub_cfg_audit.add_parser("filters", help="Report percentage of simple Gmail rules not present in unified config")
    p_cfg_audit_filters.add_argument("--in", dest="in_path", required=True, help="Unified filters YAML (filters: [])")
    p_cfg_audit_filters.add_argument("--export", dest="export_path", required=True, help="Gmail exported filters YAML (from 'filters export')")
    p_cfg_audit_filters.add_argument("--preview-missing", action="store_true", help="List a few missing simple rules")
    p_cfg_audit_filters.set_defaults(func=f_audit_filters)
