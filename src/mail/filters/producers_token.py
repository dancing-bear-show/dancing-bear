"""Token-update producers for mail filters pipelines."""
from __future__ import annotations

from core.cli_output import OutputWriter
from core.pipeline import BaseProducer

from ..providers.base import BaseProvider
from .processors_sweep import FilterTokenUpdate


def _produce_token_updates(
    client: BaseProvider,
    updates: list[FilterTokenUpdate],
    dry_run: bool,
    writer: OutputWriter,
) -> None:
    from ..utils.cli_helpers import preview_criteria as preview_crit

    changed = 0
    for update in updates:
        fid = update.filter_obj.get("id")
        if dry_run:
            writer.print_dry_run(
                f"update filter id={fid}: "
                f"{preview_crit(update.criteria)} -> from: {update.new_from}"
            )
            changed += 1
            continue
        try:
            client.create_filter(update.criteria, update.action)
            if fid:
                client.delete_filter(fid)
            writer.print(f"Updated filter id={fid}: set from={update.new_from}")
            changed += 1
        except Exception as exc:  # pragma: no cover - network
            writer.print_error(f"Failed to update filter id={fid}: {exc}")
    writer.print(f"Updated {changed} filters.")


class _TokenUpdateProducer(BaseProducer):
    """Shared wiring for the add/remove token producers."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False, writer: OutputWriter | None = None):
        super().__init__(writer)
        self.client = client
        self.dry_run = dry_run

    def _produce_success(self, payload, diagnostics: dict | None) -> None:
        _produce_token_updates(self.client, payload.updates, self.dry_run, self._writer)


class FiltersAddTokenProducer(_TokenUpdateProducer):
    """Apply add-from-token updates."""

    failure_message = "Filters add-from-token failed."


class FiltersRemoveTokenProducer(_TokenUpdateProducer):
    """Apply rm-from-token updates."""

    failure_message = "Filters rm-from-token failed."
