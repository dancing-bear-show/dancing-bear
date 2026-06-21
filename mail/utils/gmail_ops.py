"""Shared Gmail helpers for sweep/proposal flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional, Protocol


class _ListMessagesClient(Protocol):
    def list_message_ids(self, query: str | None = None, label_ids: Optional[List[str]] = None, max_pages: int = 1, page_size: int = 500) -> List[str]:
        ...

    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[dict]:
        ...


@dataclass
class MessageQueryParams:
    """Parameters for querying Gmail messages."""

    query: str
    pages: int
    max_msgs: Optional[int] = None
    page_size: Optional[int] = None


def _clip_ids(ids: List[str], max_msgs: Optional[int]) -> List[str]:
    if max_msgs is not None and len(ids) > max_msgs:
        return ids[:max_msgs]
    return ids


def list_message_ids(client: _ListMessagesClient, params: MessageQueryParams) -> List[str]:
    ids = client.list_message_ids(query=params.query, max_pages=params.pages, page_size=params.page_size or 500)
    return _clip_ids(ids, params.max_msgs)


def fetch_messages_with_metadata(
    client: _ListMessagesClient,
    params: MessageQueryParams,
) -> Tuple[List[str], List[dict]]:
    ids = list_message_ids(client, params)
    return ids, client.get_messages_metadata(ids, use_cache=True)
