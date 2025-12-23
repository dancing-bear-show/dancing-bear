from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Optional


def paginate_gmail_messages(
    svc, *, query: Optional[str] = None, label_ids: Optional[List[str]] = None, page_size: int = 500
) -> Iterator[List[str]]:
    """Yield lists of message IDs from Gmail messages.list with optional query/labels.

    - svc is a bound resource: service.users().messages()
    - Yields one list of IDs per page for efficient batch processing.
    """
    token: Optional[str] = None
    while True:
        kwargs: Dict = {"userId": "me", "maxResults": page_size}
        if query:
            kwargs["q"] = query
        if label_ids:
            kwargs["labelIds"] = label_ids
        if token:
            kwargs["pageToken"] = token
        resp: Dict = svc.list(**kwargs).execute()
        ids = [m.get("id") for m in resp.get("messages", []) if m.get("id")]
        if ids:
            yield ids
        token = resp.get("nextPageToken")
        if not token:
            break


def gather_pages(pages: Iterable[List[str]], *, max_pages: Optional[int] = None, limit: Optional[int] = None) -> List[str]:
    out: List[str] = []
    count = 0
    for ids in pages:
        out.extend(ids)
        count += 1
        if max_pages and count >= max_pages:
            break
        if limit and len(out) >= limit:
            out = out[:limit]
            break
    return out
