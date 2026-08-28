"""Producers for forwarding pipelines.

Note on the split base classes below: ForwardingList/Add use BaseProducer, but
Status/Enable/Disable deliberately do not. BaseProducer prints the diagnostics
message on its own line ("Error: <msg>"), whereas those three embed it inside a
sentence ("Failed to fetch auto-forwarding: <msg>"), and Enable additionally
branches on the message text. Expressing that through the shared template would
mean adding a formatting hook to BaseProducer for three call sites, so they keep
their hand-written produce().
"""
from __future__ import annotations

from core.cli_output import OutputWriter
from core.pipeline import BaseProducer, Producer, ResultEnvelope

from .processors import (
    ForwardingListResult,
    ForwardingAddResult,
    ForwardingStatusResult,
    ForwardingEnableResult,
    ForwardingDisableResult,
)


class ForwardingListProducer(BaseProducer):
    """Produce forwarding list output."""

    failure_message = "Failed to list forwarding addresses."

    def _produce_success(self, payload: ForwardingListResult, diagnostics: dict | None) -> None:
        for addr in payload.addresses:
            email = addr.get("forwardingEmail", "")
            status = addr.get("verificationStatus", "unknown")
            self._writer.print(f"{email}\t{status}")


class ForwardingAddProducer(BaseProducer):
    """Produce forwarding add output."""

    failure_message = "Failed to add forwarding address."

    def _produce_success(self, payload: ForwardingAddResult, diagnostics: dict | None) -> None:
        self._writer.print(
            f"Added forwarding address: {payload.email} (status: {payload.status}). "
            "Check inbox at that address to verify."
        )


class ForwardingStatusProducer(Producer[ResultEnvelope[ForwardingStatusResult]]):
    """Produce forwarding status output."""

    def __init__(self, writer: OutputWriter | None = None) -> None:
        self._writer = writer or OutputWriter()

    def produce(self, result: ResultEnvelope[ForwardingStatusResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            self._writer.print_error(f"Failed to fetch auto-forwarding: {diag.get('error', 'unknown error')}")
            return

        payload = result.payload
        self._writer.print(
            f"enabled={payload.enabled} emailAddress={payload.email_address} "
            f"disposition={payload.disposition}"
        )


class ForwardingEnableProducer(Producer[ResultEnvelope[ForwardingEnableResult]]):
    """Produce forwarding enable output."""

    def __init__(self, writer: OutputWriter | None = None) -> None:
        self._writer = writer or OutputWriter()

    def produce(self, result: ResultEnvelope[ForwardingEnableResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            error = diag.get("error", "unknown error")
            # An unverified address is the expected, actionable case, so it is
            # reported bare rather than wrapped in "Failed to enable ...".
            if "not verified" in error.lower():
                self._writer.print_error(error)
            else:
                self._writer.print_error(f"Failed to enable auto-forwarding: {error}")
            return

        payload = result.payload
        self._writer.print(
            f"Auto-forwarding enabled → {payload.email_address}; disposition={payload.disposition}"
        )


class ForwardingDisableProducer(Producer[ResultEnvelope[ForwardingDisableResult]]):
    """Produce forwarding disable output."""

    def __init__(self, writer: OutputWriter | None = None) -> None:
        self._writer = writer or OutputWriter()

    def produce(self, result: ResultEnvelope[ForwardingDisableResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            self._writer.print_error(f"Failed to disable auto-forwarding: {diag.get('error', 'unknown error')}")
            return

        self._writer.print("Auto-forwarding disabled.")
