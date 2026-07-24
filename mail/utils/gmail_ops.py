"""Shared Gmail helpers for sweep/proposal flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _ListMessagesClient(Protocol):
    def list_message_ids(self, query: str | None = None, label_ids: list[str] | None = None, max_pages: int = 1, page_size: int = 500) -> list[str]:
        ...

    def get_messages_metadata(self, ids: list[str], use_cache: bool = True) -> list[dict]:
        ...


@dataclass
class MessageQueryParams:
    """Parameters for querying Gmail messages."""

    query: str
    pages: int
    max_msgs: int | None = None
    page_size: int | None = None


def _clip_ids(ids: list[str], max_msgs: int | None) -> list[str]:
    if max_msgs is not None and len(ids) > max_msgs:
        return ids[:max_msgs]
    return ids


def list_message_ids(client: _ListMessagesClient, params: MessageQueryParams) -> list[str]:
    ids = client.list_message_ids(query=params.query, max_pages=params.pages, page_size=params.page_size or 500)
    return _clip_ids(ids, params.max_msgs)


def fetch_messages_with_metadata(
    client: _ListMessagesClient,
    params: MessageQueryParams,
) -> tuple[list[str], list[dict]]:
    ids = list_message_ids(client, params)
    return ids, client.get_messages_metadata(ids, use_cache=True)
