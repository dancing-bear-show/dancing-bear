"""Thin Gmail service wrapper built on provider helpers.

Centralizes provider construction and basic operations used by CLI
parsers for Gmail scans.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union


@dataclass
class GmailService:
    provider: Any

    @classmethod
    def from_args(cls, args: Any) -> "GmailService":
        from mail.utils.cli_helpers import gmail_provider_from_args  # lazy
        prov = gmail_provider_from_args(args)
        return cls(prov)

    def authenticate(self) -> None:
        self.provider.authenticate()

    def list_message_ids(self, *, query: str, max_pages: int, page_size: int) -> List[str]:
        return self.provider.list_message_ids(query=query, max_pages=int(max_pages), page_size=int(page_size))

    def get_message_text(self, message_id: str) -> str:
        return self.provider.get_message_text(message_id)

    def get_message(self, message_id: str):  # type: ignore[no-untyped-def]
        """Return raw message object if provider supports it."""
        return self.provider.get_message(message_id)

    # Query builders
    @staticmethod
    def build_query(
        *,
        explicit: Optional[str] = None,
        from_text: Optional[str] = None,
        days: Optional[int] = None,
        inbox_only: bool = False,
        include_terms: Optional[Union[str, Sequence[str]]] = None,
        phrase: Optional[str] = None,
    ) -> str:
        """Generic Gmail query assembler.

        - If `explicit` is provided, returns it unchanged.
        - Otherwise assembles parts: optional from:, newer_than:N d, optional in:inbox,
          optional phrase search (quoted), and optional additional OR terms.
        """
        if explicit:
            return explicit
        parts: List[str] = []
        if from_text:
            parts.append(f'from:"{from_text}"')
        if days is not None:
            parts.append(f'newer_than:{int(days)}d')
        if inbox_only:
            parts.append('in:inbox')
        if phrase:
            parts.append(f'"{phrase}"')
        if include_terms:
            if isinstance(include_terms, str):
                parts.append(include_terms)
            else:
                parts.append("(" + " OR ".join(include_terms) + ")")
        return " ".join(parts).strip()
    @staticmethod
    def build_classes_query(*, from_text: Optional[str], days: int, inbox_only: bool, explicit: Optional[str]) -> str:
        return GmailService.build_query(
            explicit=explicit,
            from_text=from_text,
            days=days,
            inbox_only=inbox_only,
        )

    @staticmethod
    def build_receipts_query(*, from_text: Optional[str], days: int, explicit: Optional[str]) -> str:
        tokens = '(Swimmer OR "Swim Kids" OR Preschool OR Bronze)'
        return GmailService.build_query(
            explicit=explicit,
            from_text=from_text,
            days=days,
            include_terms=tokens,
            phrase='Enrollment in',
        )

    @staticmethod
    def build_activerh_query(*, days: int, explicit: Optional[str] = None, programs: Optional[List[str]] = None, from_text: Optional[str] = None) -> str:
        """Construct a broad ActiveRH receipt query (delegates to build_query)."""
        progs = programs or [
            "Swimmer", "Swim Kids", "Chess", "Sportball", "Culinary", "Preschool", "Bronze",
        ]
        return GmailService.build_query(
            explicit=explicit,
            from_text=from_text,
            days=days,
            include_terms=list(progs),
            phrase='Enrollment in',
        )
