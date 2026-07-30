"""Processors for Outlook rules pipelines.

Read-only processors live here. Write/mutation processors are in processors_rules_write.py.
Helper/builder functions are in processors_rules_helpers.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    OutlookRulesListPayload,
    OutlookRulesExportPayload,
)
from .processors_rules_helpers import (  # noqa: F401
    RuleContext,
    _canon_rule,
    _fetch_rules_with_resilience,
    _build_rule_criteria,
    _build_rule_action,
    _create_rule_key,
    _build_plan_action,
    _format_plan_action,
    _build_search_query,
    _resolve_destination_folder,
    _export_rule_entry,
)
from .processors_rules_write import (  # noqa: F401
    OutlookRulesSyncResult,
    OutlookRulesPlanResult,
    OutlookRulesDeleteResult,
    OutlookRulesSweepResult,
    OutlookRulesSyncProcessor,
    OutlookRulesPlanProcessor,
    OutlookRulesDeleteProcessor,
    OutlookRulesSweepProcessor,
)


# Result dataclasses for read-only operations

@dataclass
class OutlookRulesListResult:
    """Result of rules list."""
    rules: list[dict[str, Any]] = field(default_factory=list)
    id_to_name: dict[str, str] = field(default_factory=dict)
    folder_path_rev: dict[str, str] = field(default_factory=dict)


@dataclass
class OutlookRulesExportResult:
    """Result of rules export."""
    count: int = 0
    out_path: str = ""


# Read-only processor classes

class OutlookRulesListProcessor(Processor[OutlookRulesListPayload, ResultEnvelope[OutlookRulesListResult]]):
    """List Outlook inbox rules."""

    def process(self, payload: OutlookRulesListPayload) -> ResultEnvelope[OutlookRulesListResult]:
        try:
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            name_to_id = client.get_label_id_map()
            id_to_name = {v: k for k, v in name_to_id.items() if v}
            folder_path_rev = {fid: path for path, fid in (client.get_folder_path_map() or {}).items()}
            return ResultEnvelope(
                status="success",
                payload=OutlookRulesListResult(
                    rules=rules,
                    id_to_name=id_to_name,
                    folder_path_rev=folder_path_rev,
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesExportProcessor(Processor[OutlookRulesExportPayload, ResultEnvelope[OutlookRulesExportResult]]):
    """Export Outlook inbox rules to YAML."""

    def process(self, payload: OutlookRulesExportPayload) -> ResultEnvelope[OutlookRulesExportResult]:
        try:
            from pathlib import Path
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            id_to_name = {v: k for k, v in client.get_label_id_map().items() if v}
            folder_rev = {fid: path for path, fid in (client.get_folder_path_map() or {}).items()}

            out_filters = [_export_rule_entry(r, id_to_name, folder_rev) for r in rules]

            data = {"filters": out_filters}
            from ..config_resolver import expand_path
            outp = Path(expand_path(payload.out_path))
            outp.parent.mkdir(parents=True, exist_ok=True)
            from ..yamlio import dump_config
            dump_config(str(outp), data)

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesExportResult(count=len(out_filters), out_path=str(outp)),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )
