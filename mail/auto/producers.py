from __future__ import annotations

"""Producers for auto pipelines."""

from core.pipeline import Producer, ResultEnvelope

from .processors import AutoProposeResult, AutoSummaryResult, AutoApplyResult


class AutoProposeProducer(Producer[ResultEnvelope[AutoProposeResult]]):
    """Produce auto propose output."""

    def produce(self, result: ResultEnvelope[AutoProposeResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Auto propose failed.')}")
            return

        payload = result.payload
        print(f"Proposal written to {payload.out_path} (selected {payload.selected_count} of {payload.total_considered})")


class AutoSummaryProducer(Producer[ResultEnvelope[AutoSummaryResult]]):
    """Produce auto summary output."""

    def produce(self, result: ResultEnvelope[AutoSummaryResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Auto summary failed.')}")
            return

        payload = result.payload
        print(f"Messages: {payload.message_count}")
        print("Top reasons:")
        for k, v in payload.reasons.items():
            print(f"  {k}: {v}")
        print("Label adds:")
        for k, v in payload.label_adds.items():
            print(f"  {k}: {v}")


class AutoApplyProducer(Producer[ResultEnvelope[AutoApplyResult]]):
    """Produce auto apply output."""

    def produce(self, result: ResultEnvelope[AutoApplyResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Auto apply failed.')}")
            return

        payload = result.payload
        if payload.dry_run:
            for count, add_ids, rem_ids in payload.groups:
                print(f"Would modify {count} messages; +{add_ids} -{rem_ids}")
        print(f"Applied to {payload.total_modified} messages.")
