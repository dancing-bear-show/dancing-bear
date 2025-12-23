from __future__ import annotations

"""Processors for forwarding pipelines."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    ForwardingListPayload,
    ForwardingAddPayload,
    ForwardingStatusPayload,
    ForwardingEnablePayload,
    ForwardingDisablePayload,
)


@dataclass
class ForwardingListResult:
    """Result of forwarding list."""

    addresses: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ForwardingAddResult:
    """Result of forwarding add."""

    email: str
    status: str


@dataclass
class ForwardingStatusResult:
    """Result of forwarding status."""

    enabled: bool
    email_address: str
    disposition: str


@dataclass
class ForwardingEnableResult:
    """Result of forwarding enable."""

    email_address: str
    disposition: str


@dataclass
class ForwardingDisableResult:
    """Result of forwarding disable."""

    success: bool = True


class ForwardingListProcessor(Processor[ForwardingListPayload, ResultEnvelope[ForwardingListResult]]):
    """List forwarding addresses."""

    def process(self, payload: ForwardingListPayload) -> ResultEnvelope[ForwardingListResult]:
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()
            infos = client.list_forwarding_addresses_info()
            return ResultEnvelope(
                status="success",
                payload=ForwardingListResult(addresses=infos),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class ForwardingAddProcessor(Processor[ForwardingAddPayload, ResultEnvelope[ForwardingAddResult]]):
    """Add a forwarding address."""

    def process(self, payload: ForwardingAddPayload) -> ResultEnvelope[ForwardingAddResult]:
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()
            resp = client.create_forwarding_address(payload.email)
            status = resp.get("verificationStatus") or "pending"
            return ResultEnvelope(
                status="success",
                payload=ForwardingAddResult(email=payload.email, status=status),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class ForwardingStatusProcessor(Processor[ForwardingStatusPayload, ResultEnvelope[ForwardingStatusResult]]):
    """Get auto-forwarding status."""

    def process(self, payload: ForwardingStatusPayload) -> ResultEnvelope[ForwardingStatusResult]:
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()
            st = client.get_auto_forwarding()
            return ResultEnvelope(
                status="success",
                payload=ForwardingStatusResult(
                    enabled=st.get("enabled", False),
                    email_address=st.get("emailAddress") or "",
                    disposition=st.get("disposition") or "",
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 2},
            )


class ForwardingEnableProcessor(Processor[ForwardingEnablePayload, ResultEnvelope[ForwardingEnableResult]]):
    """Enable auto-forwarding."""

    def process(self, payload: ForwardingEnablePayload) -> ResultEnvelope[ForwardingEnableResult]:
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()

            # Verify destination is in verified list
            try:
                verified = set(client.get_verified_forwarding_addresses())
            except Exception:
                verified = set()

            if verified and payload.email not in verified:
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": f"Forward address not verified: {payload.email}", "code": 2},
                )

            st = client.set_auto_forwarding(
                enabled=True,
                email=payload.email,
                disposition=payload.disposition,
            )
            return ResultEnvelope(
                status="success",
                payload=ForwardingEnableResult(
                    email_address=st.get("emailAddress", ""),
                    disposition=st.get("disposition", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class ForwardingDisableProcessor(Processor[ForwardingDisablePayload, ResultEnvelope[ForwardingDisableResult]]):
    """Disable auto-forwarding."""

    def process(self, payload: ForwardingDisablePayload) -> ResultEnvelope[ForwardingDisableResult]:
        try:
            client = payload.context.get_gmail_client()
            client.authenticate()
            client.set_auto_forwarding(enabled=False)
            return ResultEnvelope(
                status="success",
                payload=ForwardingDisableResult(success=True),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )
