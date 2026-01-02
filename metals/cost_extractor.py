"""Base class for extracting precious metals costs from email providers.

Provides template method pattern for cost extraction workflow, reducing complexity
in gmail_costs and outlook_costs by encapsulating common logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

from .costs_common import merge_costs_csv


@dataclass
class MessageInfo:
    """Normalized message metadata across providers."""
    msg_id: str
    subject: str
    from_header: str
    body_text: str
    received_date: str  # ISO format or provider-specific
    received_ms: int = 0  # Timestamp in milliseconds (Gmail uses this)


@dataclass
class OrderData:
    """Data for a single order to be processed."""
    order_id: str
    messages: List[MessageInfo]
    vendor: str


class CostExtractor(ABC):
    """Base class for cost extraction from email providers.

    Template method pattern: run() orchestrates the workflow,
    calling abstract methods for provider-specific operations.
    """

    def __init__(self, profile: str, out_path: str, days: int = 365):
        """Initialize extractor.

        Args:
            profile: Credential profile name
            out_path: Output CSV path
            days: Time window for message search
        """
        self.profile = profile
        self.out_path = out_path
        self.days = days
        self.client = None

    @abstractmethod
    def _authenticate(self) -> None:
        """Authenticate with email provider and set self.client."""
        raise NotImplementedError

    @abstractmethod
    def _fetch_message_ids(self) -> List[str]:
        """Fetch message IDs matching vendor search criteria.

        Returns:
            List of message IDs to process.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_message_info(self, msg_id: str) -> MessageInfo:
        """Get normalized message information.

        Args:
            msg_id: Message identifier.

        Returns:
            Normalized message info.
        """
        raise NotImplementedError

    @abstractmethod
    def _extract_order_id(self, msg: MessageInfo) -> Optional[str]:
        """Extract order ID from message.

        Args:
            msg: Message info.

        Returns:
            Order ID if found, else None.
        """
        raise NotImplementedError

    @abstractmethod
    def _select_best_message(self, messages: List[MessageInfo]) -> MessageInfo:
        """Select the best message to use for an order.

        Args:
            messages: All messages for an order.

        Returns:
            Best message (e.g., confirmation over shipping).
        """
        raise NotImplementedError

    @abstractmethod
    def _process_order_to_rows(self, order: OrderData) -> List[Dict[str, str | float]]:
        """Process a single order into output rows.

        This is the main provider-specific logic for extracting costs.

        Args:
            order: Order data with messages.

        Returns:
            List of CSV row dicts.
        """
        raise NotImplementedError

    def _group_by_order(self, ids: List[str]) -> Dict[str, List[MessageInfo]]:
        """Group messages by order ID (common logic).

        Args:
            ids: Message IDs to process.

        Returns:
            Dict mapping order_id to list of messages.
        """
        by_order: Dict[str, List[MessageInfo]] = {}
        for msg_id in ids:
            msg = self._get_message_info(msg_id)
            oid = self._extract_order_id(msg)
            if oid:
                by_order.setdefault(oid, []).append(msg)
        return by_order

    def _build_order_data(self, order_id: str, messages: List[MessageInfo]) -> OrderData:
        """Build OrderData from grouped messages.

        Args:
            order_id: Order identifier.
            messages: Messages for this order.

        Returns:
            OrderData with best message selected.
        """
        best_msg = self._select_best_message(messages)
        vendor = self._classify_vendor(best_msg.from_header)
        return OrderData(order_id=order_id, messages=messages, vendor=vendor)

    def _classify_vendor(self, from_header: str) -> str:
        """Classify vendor from sender (can be overridden).

        Args:
            from_header: Email from header.

        Returns:
            Vendor name.
        """
        return 'Unknown'

    def run(self) -> int:
        """Template method: orchestrate cost extraction workflow.

        Workflow:
        1. Authenticate
        2. Fetch message IDs
        3. Group by order
        4. Process each order
        5. Merge results to CSV

        Returns:
            0 if costs were extracted and merged, 1 if no costs found.
        """
        self._authenticate()
        ids = self._fetch_message_ids()

        if not ids:
            print('no messages found')
            return 0

        by_order = self._group_by_order(ids)

        if not by_order:
            print('no orders found')
            return 0

        out_rows: List[Dict[str, str | float]] = []
        for oid, messages in by_order.items():
            order = self._build_order_data(oid, messages)
            rows = self._process_order_to_rows(order)
            out_rows.extend(rows)

        if out_rows:
            merge_costs_csv(self.out_path, out_rows)
            print(f"merged {len(out_rows)} row(s) into {self.out_path}")
            return 0
        else:
            print('messages found but no costs extracted')
            return 1


__all__ = ['CostExtractor', 'MessageInfo', 'OrderData']
