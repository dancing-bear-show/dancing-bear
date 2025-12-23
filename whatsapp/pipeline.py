from __future__ import annotations

"""WhatsApp pipeline primitives built on shared core scaffolding."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.pipeline import BaseProducer, Processor, RequestConsumer, ResultEnvelope

from .search import MessageRow, format_rows_json, format_rows_text, search_messages


@dataclass
class SearchRequest:
    """Search parameters for WhatsApp message lookup."""

    db_path: Optional[str] = None
    contains: Optional[List[str]] = None
    match_all: bool = False
    contact: Optional[str] = None
    from_me: Optional[bool] = None
    since_days: Optional[int] = None
    limit: int = 50
    emit_json: bool = False


# Type alias for backward compatibility
SearchRequestConsumer = RequestConsumer[SearchRequest]


@dataclass
class SearchResult:
    """Container for search results and output preferences."""

    rows: List[MessageRow]
    emit_json: bool = False


class SearchProcessor(Processor[SearchRequest, ResultEnvelope[SearchResult]]):
    """Execute WhatsApp search and return results in envelope."""

    def process(self, payload: SearchRequest) -> ResultEnvelope[SearchResult]:
        try:
            rows = search_messages(
                db_path=payload.db_path,
                contains=payload.contains,
                match_all=payload.match_all,
                contact=payload.contact,
                from_me=payload.from_me,
                since_days=payload.since_days,
                limit=payload.limit,
            )
            result = SearchResult(rows=rows, emit_json=payload.emit_json)
            return ResultEnvelope(status="success", payload=result)
        except FileNotFoundError as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"code": 2, "error": str(exc), "hint": "db_not_found"},
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"code": 1, "error": str(exc)},
            )


class SearchProducer(BaseProducer):
    """Output search results to stdout (text or JSON)."""

    def _produce_success(self, payload: SearchResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        if payload.emit_json:
            print(format_rows_json(payload.rows))
        else:
            print(format_rows_text(payload.rows))
