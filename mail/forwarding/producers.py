from __future__ import annotations

"""Producers for forwarding pipelines."""

from core.pipeline import Producer, ResultEnvelope

from .processors import (
    ForwardingListResult,
    ForwardingAddResult,
    ForwardingStatusResult,
    ForwardingEnableResult,
    ForwardingDisableResult,
)


class ForwardingListProducer(Producer[ResultEnvelope[ForwardingListResult]]):
    """Produce forwarding list output."""

    def produce(self, result: ResultEnvelope[ForwardingListResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to list forwarding addresses.')}")
            return

        for addr in result.payload.addresses:
            email = addr.get("forwardingEmail", "")
            status = addr.get("verificationStatus", "unknown")
            print(f"{email}\t{status}")


class ForwardingAddProducer(Producer[ResultEnvelope[ForwardingAddResult]]):
    """Produce forwarding add output."""

    def produce(self, result: ResultEnvelope[ForwardingAddResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Error: {diag.get('error', 'Failed to add forwarding address.')}")
            return

        payload = result.payload
        print(f"Added forwarding address: {payload.email} (status: {payload.status}). Check inbox at that address to verify.")


class ForwardingStatusProducer(Producer[ResultEnvelope[ForwardingStatusResult]]):
    """Produce forwarding status output."""

    def produce(self, result: ResultEnvelope[ForwardingStatusResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Failed to fetch auto-forwarding: {diag.get('error', 'unknown error')}")
            return

        payload = result.payload
        print(f"enabled={payload.enabled} emailAddress={payload.email_address} disposition={payload.disposition}")


class ForwardingEnableProducer(Producer[ResultEnvelope[ForwardingEnableResult]]):
    """Produce forwarding enable output."""

    def produce(self, result: ResultEnvelope[ForwardingEnableResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            error = diag.get("error", "unknown error")
            if "not verified" in error.lower():
                print(f"Error: {error}")
            else:
                print(f"Failed to enable auto-forwarding: {error}")
            return

        payload = result.payload
        print(f"Auto-forwarding enabled → {payload.email_address}; disposition={payload.disposition}")


class ForwardingDisableProducer(Producer[ResultEnvelope[ForwardingDisableResult]]):
    """Produce forwarding disable output."""

    def produce(self, result: ResultEnvelope[ForwardingDisableResult]) -> None:
        if not result.ok() or not result.payload:
            diag = result.diagnostics or {}
            print(f"Failed to disable auto-forwarding: {diag.get('error', 'unknown error')}")
            return

        print("Auto-forwarding disabled.")
