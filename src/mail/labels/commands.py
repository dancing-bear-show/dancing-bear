"""Re-export shim: labels command orchestration helpers.

Plan/sync/export pipeline commands live in commands_plan.py.
Doctor/health commands live in commands_doctor.py.
"""
from __future__ import annotations

from .commands_plan import (  # noqa: F401
    _analyze_labels,
    _run_labels_pipeline,
    run_labels_plan,
    run_labels_sync,
    run_labels_export,
    run_labels_list,
)
from .commands_doctor import (  # noqa: F401
    run_labels_doctor,
    _print_doctor_report,
    _fix_label_visibility,
    _redirect_imap_labels,
    _delete_imap_labels,
    run_labels_prune_empty,
    _delete_label_with_retry,
    _get_empty_user_labels,
    run_labels_learn,
    _extract_email_from_header,
    _extract_domain,
    _pattern_matches,
    _is_protected_sender,
    _classify_domain,
    _collect_domain_stats,
    _apply_one_suggestion,
    run_labels_apply_suggestions,
    run_labels_delete,
    run_labels_sweep_parents,
)
