"""Re-export shim: pipeline primitives for derive, optimize, audit, and env-setup config commands.

Actual implementations live in pipeline_derive.py and pipeline_audit.py.
"""
from __future__ import annotations

from .pipeline_derive import (  # noqa: F401
    DeriveLabelsRequest,
    DeriveLabelsResult,
    DeriveLabelsRequestConsumer,
    DeriveLabelsProcessor,
    DeriveLabelsProducer,
    DeriveFiltersRequest,
    DeriveFiltersResult,
    DeriveFiltersRequestConsumer,
    _apply_archive_on_remove_inbox,
    _apply_move_to_folders,
    DeriveFiltersProcessor,
    DeriveFiltersProducer,
    OptimizeFiltersRequest,
    MergedGroup,
    OptimizeFiltersResult,
    OptimizeFiltersRequestConsumer,
    _partition_rules_by_dest,
    _merge_group,
    OptimizeFiltersProcessor,
    OptimizeFiltersProducer,
)
from .pipeline_audit import (  # noqa: F401
    AuditFiltersRequest,
    AuditFiltersResult,
    AuditFiltersRequestConsumer,
    _build_dest_token_map,
    _extract_filter_from_addr,
    _extract_filter_adds,
    _token_matches,
    _score_exported_filters,
    AuditFiltersProcessor,
    AuditFiltersProducer,
    EnvSetupRequest,
    EnvSetupResult,
    EnvSetupRequestConsumer,
    _setup_venv,
    _resolve_gmail_cred_paths,
    EnvSetupProcessor,
    EnvSetupProducer,
)
