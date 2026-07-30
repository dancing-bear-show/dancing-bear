"""Pipeline primitives for config commands.

Thin re-export shim. Implementation lives in:
- pipeline_cache.py       — Auth, Backup, CacheStats, CacheClear, CachePrune, ConfigInspect
- pipeline_auth_backup.py — DeriveLabels, DeriveFilters, OptimizeFilters, AuditFilters, EnvSetup
"""
from __future__ import annotations

# Re-export from core.pipeline so callers can do `from .pipeline import RequestConsumer`
from core.pipeline import RequestConsumer  # noqa: F401

from mail.config_cli.pipeline_cache import (  # noqa: F401
    AuthRequest,
    AuthResult,
    AuthRequestConsumer,
    AuthProcessor,
    AuthProducer,
    BackupRequest,
    BackupResult,
    BackupRequestConsumer,
    BackupProcessor,
    BackupProducer,
    CacheStatsRequest,
    CacheStatsResult,
    CacheStatsRequestConsumer,
    CacheStatsProcessor,
    CacheStatsProducer,
    CacheClearRequest,
    CacheClearResult,
    CacheClearRequestConsumer,
    CacheClearProcessor,
    CacheClearProducer,
    CachePruneRequest,
    CachePruneResult,
    CachePruneRequestConsumer,
    CachePruneProcessor,
    CachePruneProducer,
    ConfigInspectRequest,
    ConfigSection,
    ConfigInspectResult,
    ConfigInspectRequestConsumer,
    ConfigInspectProcessor,
    ConfigInspectProducer,
)

from mail.config_cli.pipeline_auth_backup import (  # noqa: F401
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
