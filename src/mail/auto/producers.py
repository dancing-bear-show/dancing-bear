"""Producers for auto pipelines."""
from __future__ import annotations

from core.pipeline import BaseProducer

from .processors import AutoProposeResult, AutoSummaryResult, AutoApplyResult


class AutoProposeProducer(BaseProducer):
    """Produce auto propose output."""

    failure_message = "Auto propose failed."

    def _produce_success(self, payload: AutoProposeResult, diagnostics: dict | None) -> None:
        self._writer.print(
            f"Proposal written to {payload.out_path} "
            f"(selected {payload.selected_count} of {payload.total_considered})"
        )


class AutoSummaryProducer(BaseProducer):
    """Produce auto summary output."""

    failure_message = "Auto summary failed."

    def _produce_success(self, payload: AutoSummaryResult, diagnostics: dict | None) -> None:
        self._writer.print(f"Messages: {payload.message_count}")
        self._writer.print("Top reasons:")
        for k, v in payload.reasons.items():
            self._writer.print(f"  {k}: {v}")
        self._writer.print("Label adds:")
        for k, v in payload.label_adds.items():
            self._writer.print(f"  {k}: {v}")


class AutoApplyProducer(BaseProducer):
    """Produce auto apply output."""

    failure_message = "Auto apply failed."

    def _produce_success(self, payload: AutoApplyResult, diagnostics: dict | None) -> None:
        if payload.dry_run:
            for count, add_ids, rem_ids in payload.groups:
                self._writer.print_dry_run(f"modify {count} messages; +{add_ids} -{rem_ids}")
        self._writer.print(f"Applied to {payload.total_modified} messages.")
