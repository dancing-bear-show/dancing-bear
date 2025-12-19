"""Shared Gmail helpers for sweep/proposal flows."""

from __future__ import annotations

from typing import List, Tuple, Optional, Protocol, Any


class _ListMessagesClient(Protocol):
    def list_message_ids(self, query: str | None = None, label_ids: Optional[List[str]] = None, max_pages: int = 1, page_size: int = 500) -> List[str]:
        ...

    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[dict]:
        ...


def _clip_ids(ids: List[str], max_msgs: Optional[int]) -> List[str]:
    if max_msgs is not None and len(ids) > max_msgs:
        return ids[:max_msgs]
    return ids


def list_message_ids(client: _ListMessagesClient, *, query: str, pages: int, max_msgs: Optional[int] = None, page_size: Optional[int] = None) -> List[str]:
    ids = client.list_message_ids(query=query, max_pages=pages, page_size=page_size or 500)
    return _clip_ids(ids, max_msgs)


def fetch_messages_with_metadata(
    client: _ListMessagesClient,
    *,
    query: str,
    pages: int,
    max_msgs: Optional[int] = None,
    page_size: Optional[int] = None,
) -> Tuple[List[str], List[dict]]:
    ids = list_message_ids(client, query=query, pages=pages, max_msgs=max_msgs, page_size=page_size)
    return ids, client.get_messages_metadata(ids, use_cache=True)
