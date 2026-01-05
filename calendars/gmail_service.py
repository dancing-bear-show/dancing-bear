"""Thin Gmail service wrapper built on provider helpers.

Centralizes provider construction and basic operations used by CLI
parsers for Gmail scans.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union


@dataclass
class QueryParams:
    """Parameters for building Gmail queries."""

    explicit: Optional[str] = None
    from_text: Optional[str] = None
    days: Optional[int] = None
    inbox_only: bool = False
    include_terms: Optional[Union[str, Sequence[str]]] = None
    phrase: Optional[str] = None


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
    def build_query_from_params(params: QueryParams) -> str:
        """Generic Gmail query assembler using QueryParams.

        - If `explicit` is provided, returns it unchanged.
        - Otherwise assembles parts: optional from:, newer_than:N d, optional in:inbox,
          optional phrase search (quoted), and optional additional OR terms.
        """
        if params.explicit:
            return params.explicit
        parts: List[str] = []
        if params.from_text:
            parts.append(f'from:"{params.from_text}"')
        if params.days is not None:
            parts.append(f'newer_than:{int(params.days)}d')
        if params.inbox_only:
            parts.append('in:inbox')
        if params.phrase:
            parts.append(f'"{params.phrase}"')
        if params.include_terms:
            if isinstance(params.include_terms, str):
                parts.append(params.include_terms)
            else:
                parts.append("(" + " OR ".join(params.include_terms) + ")")
        return " ".join(parts).strip()

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
        """Generic Gmail query assembler (legacy signature).

        Delegates to build_query_from_params for implementation.
        """
        params = QueryParams(
            explicit=explicit,
            from_text=from_text,
            days=days,
            inbox_only=inbox_only,
            include_terms=include_terms,
            phrase=phrase,
        )
        return GmailService.build_query_from_params(params)
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
