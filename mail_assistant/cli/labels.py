from __future__ import annotations

"""Labels CLI registration.

Keeps `__main__` lean by wiring the `labels` group here while preserving
existing flags and subcommands.
"""


def register(
    subparsers,
    *,
    f_list,
    f_sync,
    f_export,
    f_plan,
    f_doctor,
    f_prune_empty,
    f_learn,
    f_apply_suggestions,
    f_delete,
    f_sweep_parents,
):
    p_labels = subparsers.add_parser("labels", help="Label operations")
    # Group-level common Gmail args
    p_labels.add_argument("--credentials", type=str)
    p_labels.add_argument("--token", type=str)
    p_labels.add_argument("--cache", type=str, help="Cache directory (optional)")
    sub_labels = p_labels.add_subparsers(dest="labels_cmd")

    # list (default)
    p_labels_list = sub_labels.add_parser("list", help="List labels")
    p_labels_list.set_defaults(func=f_list)

    # sync
    p_labels_sync = sub_labels.add_parser("sync", help="Sync labels from YAML config")
    p_labels_sync.add_argument("--config", required=True, help="Path to YAML config with labels[]")
    p_labels_sync.add_argument("--dry-run", action="store_true", help="Do not make changes")
    p_labels_sync.add_argument(
        "--delete-missing", action="store_true", help="Delete labels not present in config (skips system labels)"
    )
    p_labels_sync.add_argument(
        "--sweep-redirects",
        action="store_true",
        help="Apply 'redirects' by relabeling messages from old->new then deleting old",
    )
    p_labels_sync.set_defaults(func=f_sync)

    # export
    p_labels_export = sub_labels.add_parser("export", help="Export current labels to a YAML file")
    p_labels_export.add_argument("--out", required=True, help="Output YAML path")
    p_labels_export.set_defaults(func=f_export)

    # plan
    p_labels_plan = sub_labels.add_parser("plan", help="Plan label changes from YAML (no apply)")
    p_labels_plan.add_argument("--config", required=True, help="Path to YAML config with labels[]")
    p_labels_plan.add_argument(
        "--delete-missing",
        action="store_true",
        help="Show user labels that would be deleted (not present in YAML)",
    )
    p_labels_plan.set_defaults(func=f_plan)

    # doctor
    p_labels_doctor = sub_labels.add_parser("doctor", help="Analyze labels and optionally enforce defaults")
    p_labels_doctor.add_argument(
        "--set-visibility", action="store_true", help="Set default visibility on labels missing it"
    )
    p_labels_doctor.add_argument(
        "--imap-redirect", action="append", default=[], help="Redirect IMAP-style label old=new (can be repeated)"
    )
    p_labels_doctor.add_argument(
        "--imap-delete", action="append", default=[], help="Delete listed labels after redirect (can be repeated)"
    )
    p_labels_doctor.add_argument("--use-cache", action="store_true", help="Use cached labels (if cache configured)")
    p_labels_doctor.add_argument("--cache-ttl", type=int, default=300, help="Cache TTL seconds")
    p_labels_doctor.set_defaults(func=f_doctor)

    # prune-empty
    p_labels_prune = sub_labels.add_parser("prune-empty", help="Delete user labels with zero messages")
    p_labels_prune.add_argument("--dry-run", action="store_true")
    p_labels_prune.add_argument("--limit", type=int, default=0, help="Max deletions this run (0 = no limit)")
    p_labels_prune.add_argument("--sleep-sec", type=float, default=0.0, help="Sleep seconds between deletions")
    p_labels_prune.set_defaults(func=f_prune_empty)

    # learn
    p_labels_learn = sub_labels.add_parser(
        "learn", help="Propose sender/domain → label mappings from recent mail"
    )
    # Allow common args after subcommand for convenience
    p_labels_learn.add_argument("--credentials", type=str)
    p_labels_learn.add_argument("--token", type=str)
    p_labels_learn.add_argument("--cache", type=str)
    p_labels_learn.add_argument("--days", type=int, default=30)
    p_labels_learn.add_argument("--only-inbox", action="store_true")
    p_labels_learn.add_argument("--min-count", type=int, default=5, help="Minimum occurrences to suggest")
    p_labels_learn.add_argument("--out", required=True)
    p_labels_learn.add_argument(
        "--protect", action="append", default=[], help="Protected senders/domains to skip"
    )
    p_labels_learn.set_defaults(func=f_learn)

    # apply-suggestions
    p_labels_apply_sug = sub_labels.add_parser(
        "apply-suggestions", help="Create filters from a learn proposal (and optional sweep)"
    )
    p_labels_apply_sug.add_argument("--credentials", type=str)
    p_labels_apply_sug.add_argument("--token", type=str)
    p_labels_apply_sug.add_argument("--cache", type=str)
    p_labels_apply_sug.add_argument("--config", required=True, help="Learn proposal YAML")
    p_labels_apply_sug.add_argument("--dry-run", action="store_true")
    p_labels_apply_sug.add_argument(
        "--sweep-days", type=int, help="After creating filters, sweep back N days"
    )
    p_labels_apply_sug.add_argument("--pages", type=int, default=50)
    p_labels_apply_sug.add_argument("--batch-size", type=int, default=500)
    p_labels_apply_sug.set_defaults(func=f_apply_suggestions)

    # delete by name
    p_labels_del = sub_labels.add_parser("delete", help="Delete a user label by name")
    p_labels_del.add_argument("--name", required=True, help="Exact label name to delete (e.g., Personal/Alumni)")
    p_labels_del.add_argument("--credentials", type=str)
    p_labels_del.add_argument("--token", type=str)
    p_labels_del.add_argument("--cache", type=str)
    p_labels_del.set_defaults(func=f_delete)

    # sweep-parents
    p_labels_sweep_parents = sub_labels.add_parser(
        "sweep-parents", help="Add parent label when any child label exists (e.g., Kids/* -> Kids)"
    )
    p_labels_sweep_parents.add_argument("--credentials", type=str)
    p_labels_sweep_parents.add_argument("--token", type=str)
    p_labels_sweep_parents.add_argument("--cache", type=str)
    p_labels_sweep_parents.add_argument(
        "--names", required=True, help="Comma-separated parent label names to enforce (e.g., Kids,Lists)"
    )
    p_labels_sweep_parents.add_argument("--pages", type=int, default=50)
    p_labels_sweep_parents.add_argument("--batch-size", type=int, default=500)
    p_labels_sweep_parents.add_argument("--dry-run", action="store_true")
    p_labels_sweep_parents.set_defaults(func=f_sweep_parents)

    # If no subcommand is provided after 'labels', default to list
    p_labels.set_defaults(func=f_list)
