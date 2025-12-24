from __future__ import annotations

def register(subparsers, *, f_propose, f_apply, f_summary):
    p_auto = subparsers.add_parser(
        "auto", help="Gmail: propose/apply categorization + archive for low-interest inbox mail"
    )
    sub_auto = p_auto.add_subparsers(dest="auto_cmd")
    common_auto = {
        "--credentials": {"type": str},
        "--token": {"type": str},
        "--cache": {"type": str},
        "--days": {"type": int, "default": 7},
        "--only-inbox": {"action": "store_true"},
        "--pages": {"type": int, "default": 20},
        "--batch-size": {"type": int, "default": 500},
        "--log": {"type": str, "default": "logs/auto_runs.jsonl"},
    }
    p_auto_propose = sub_auto.add_parser(
        "propose", help="Create a proposal for categorizing + archiving low-interest mail"
    )
    for k, v in common_auto.items():
        p_auto_propose.add_argument(k, **v)
    p_auto_propose.add_argument("--out", required=True, help="Path to proposal JSON")
    p_auto_propose.add_argument("--dry-run", action="store_true")
    p_auto_propose.set_defaults(func=f_propose)

    p_auto_apply = sub_auto.add_parser("apply", help="Apply a saved proposal (archive + label)")
    p_auto_apply.add_argument("--credentials", type=str)
    p_auto_apply.add_argument("--token", type=str)
    p_auto_apply.add_argument("--cache", type=str)
    p_auto_apply.add_argument("--proposal", required=True)
    p_auto_apply.add_argument("--cutoff-days", type=int, help="Only apply to messages older than N days")
    p_auto_apply.add_argument("--batch-size", type=int, default=500)
    p_auto_apply.add_argument("--dry-run", action="store_true")
    p_auto_apply.add_argument("--log", type=str, default="logs/auto_runs.jsonl")
    p_auto_apply.set_defaults(func=f_apply)

    p_auto_summary = sub_auto.add_parser("summary", help="Summarize a proposal JSON")
    p_auto_summary.add_argument("--proposal", required=True)
    p_auto_summary.set_defaults(func=f_summary)

