"""Accounts command orchestration helpers for multi-account operations."""
from __future__ import annotations

from .pipeline import (
    AccountsListRequest,
    AccountsListRequestConsumer,
    AccountsListProcessor,
    AccountsListProducer,
    AccountsExportLabelsRequest,
    AccountsExportLabelsRequestConsumer,
    AccountsExportLabelsProcessor,
    AccountsExportLabelsProducer,
    AccountsSyncLabelsRequest,
    AccountsSyncLabelsRequestConsumer,
    AccountsSyncLabelsProcessor,
    AccountsSyncLabelsProducer,
    AccountsExportFiltersRequest,
    AccountsExportFiltersRequestConsumer,
    AccountsExportFiltersProcessor,
    AccountsExportFiltersProducer,
    AccountsSyncFiltersRequest,
    AccountsSyncFiltersRequestConsumer,
    AccountsSyncFiltersProcessor,
    AccountsSyncFiltersProducer,
    AccountsPlanLabelsRequest,
    AccountsPlanLabelsRequestConsumer,
    AccountsPlanLabelsProcessor,
    AccountsPlanLabelsProducer,
    AccountsPlanFiltersRequest,
    AccountsPlanFiltersRequestConsumer,
    AccountsPlanFiltersProcessor,
    AccountsPlanFiltersProducer,
    AccountsExportSignaturesRequest,
    AccountsExportSignaturesRequestConsumer,
    AccountsExportSignaturesProcessor,
    AccountsExportSignaturesProducer,
    AccountsSyncSignaturesRequest,
    AccountsSyncSignaturesRequestConsumer,
    AccountsSyncSignaturesProcessor,
    AccountsSyncSignaturesProducer,
)


def run_accounts_list(args) -> int:
    """List all configured accounts."""
    request = AccountsListRequest(config_path=args.config)
    envelope = AccountsListProcessor().process(
        AccountsListRequestConsumer(request).consume()
    )
    AccountsListProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_export_labels(args) -> int:
    """Export labels from all accounts to YAML files."""
    request = AccountsExportLabelsRequest(
        config_path=args.config,
        out_dir=args.out_dir,
        accounts_filter=getattr(args, "accounts", None),
    )
    envelope = AccountsExportLabelsProcessor().process(
        AccountsExportLabelsRequestConsumer(request).consume()
    )
    AccountsExportLabelsProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_sync_labels(args) -> int:
    """Sync labels to all accounts from a YAML config."""
    dry_run = getattr(args, "dry_run", False)
    request = AccountsSyncLabelsRequest(
        config_path=args.config,
        labels_path=args.labels,
        accounts_filter=getattr(args, "accounts", None),
        dry_run=dry_run,
    )
    envelope = AccountsSyncLabelsProcessor().process(
        AccountsSyncLabelsRequestConsumer(request).consume()
    )
    AccountsSyncLabelsProducer(dry_run=dry_run).produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_export_filters(args) -> int:
    """Export filters from all accounts to YAML files."""
    request = AccountsExportFiltersRequest(
        config_path=args.config,
        out_dir=args.out_dir,
        accounts_filter=getattr(args, "accounts", None),
    )
    envelope = AccountsExportFiltersProcessor().process(
        AccountsExportFiltersRequestConsumer(request).consume()
    )
    AccountsExportFiltersProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_sync_filters(args) -> int:
    """Sync filters to all accounts from a YAML config."""
    dry_run = getattr(args, "dry_run", False)
    request = AccountsSyncFiltersRequest(
        config_path=args.config,
        filters_path=args.filters,
        accounts_filter=getattr(args, "accounts", None),
        dry_run=dry_run,
        require_forward_verified=getattr(args, "require_forward_verified", False),
    )
    envelope = AccountsSyncFiltersProcessor().process(
        AccountsSyncFiltersRequestConsumer(request).consume()
    )
    AccountsSyncFiltersProducer(dry_run=dry_run).produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_plan_labels(args) -> int:
    """Plan labels changes for all accounts."""
    request = AccountsPlanLabelsRequest(
        config_path=args.config,
        labels_path=args.labels,
        accounts_filter=getattr(args, "accounts", None),
    )
    envelope = AccountsPlanLabelsProcessor().process(
        AccountsPlanLabelsRequestConsumer(request).consume()
    )
    AccountsPlanLabelsProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_plan_filters(args) -> int:
    """Plan filters changes for all accounts."""
    request = AccountsPlanFiltersRequest(
        config_path=args.config,
        filters_path=args.filters,
        accounts_filter=getattr(args, "accounts", None),
    )
    envelope = AccountsPlanFiltersProcessor().process(
        AccountsPlanFiltersRequestConsumer(request).consume()
    )
    AccountsPlanFiltersProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_export_signatures(args) -> int:
    """Export signatures from all accounts to YAML files."""
    request = AccountsExportSignaturesRequest(
        config_path=args.config,
        out_dir=args.out_dir,
        accounts_filter=getattr(args, "accounts", None),
    )
    envelope = AccountsExportSignaturesProcessor().process(
        AccountsExportSignaturesRequestConsumer(request).consume()
    )
    AccountsExportSignaturesProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_accounts_sync_signatures(args) -> int:
    """Sync signatures to all accounts from a YAML config."""
    request = AccountsSyncSignaturesRequest(
        config_path=args.config,
        accounts_filter=getattr(args, "accounts", None),
        send_as=getattr(args, "send_as", None),
        dry_run=getattr(args, "dry_run", False),
    )
    envelope = AccountsSyncSignaturesProcessor().process(
        AccountsSyncSignaturesRequestConsumer(request).consume()
    )
    AccountsSyncSignaturesProducer().produce(envelope)
    return 0 if envelope.ok() else 1
