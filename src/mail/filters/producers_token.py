"""Token-update producers for mail filters pipelines."""
from __future__ import annotations

from core.pipeline import Producer, ResultEnvelope

from ..providers.base import BaseProvider
from .processors_sweep import (
    FiltersAddTokenResult,
    FiltersRemoveTokenResult,
    FilterTokenUpdate,
)


def _produce_token_updates(client: BaseProvider, updates: list[FilterTokenUpdate], dry_run: bool) -> None:
    from ..utils.cli_helpers import preview_criteria as preview_crit

    changed = 0
    for update in updates:
        fid = update.filter_obj.get("id")
        if dry_run:
            print(
                f"Would update filter id={fid}: "
                f"{preview_crit(update.criteria)} -> from: {update.new_from}"
            )
            changed += 1
            continue
        try:
            client.create_filter(update.criteria, update.action)
            if fid:
                client.delete_filter(fid)
            print(f"Updated filter id={fid}: set from={update.new_from}")
            changed += 1
        except Exception as exc:  # pragma: no cover - network
            print(f"Failed to update filter id={fid}: {exc}")
    print(f"Updated {changed} filters.")


class FiltersAddTokenProducer(Producer[ResultEnvelope[FiltersAddTokenResult]]):
    """Apply add-from-token updates."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersAddTokenResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters add-from-token failed.")
            return
        _produce_token_updates(self.client, result.payload.updates, self.dry_run)


class FiltersRemoveTokenProducer(Producer[ResultEnvelope[FiltersRemoveTokenResult]]):
    """Apply rm-from-token updates."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersRemoveTokenResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters rm-from-token failed.")
            return
        _produce_token_updates(self.client, result.payload.updates, self.dry_run)
