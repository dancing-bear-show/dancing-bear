"""Sweep producers for mail filters pipelines."""
from __future__ import annotations

from dataclasses import dataclass
import time

from core.pipeline import Producer, ResultEnvelope

from ..providers.base import BaseProvider
from ..utils.batch import apply_in_chunks
from ..utils.gmail_ops import list_message_ids as _list_message_ids_shared, MessageQueryParams
from .processors import (
    FiltersPruneResult,
    FiltersSweepResult,
    FiltersSweepRangeResult,
)

_EMPTY_QUERY = "(empty)"


@dataclass
class SweepProducerConfig:
    """Configuration for sweep producer operations."""

    pages: int
    batch_size: int
    max_msgs: int | None
    dry_run: bool = False


class FiltersSweepProducer(Producer[ResultEnvelope[FiltersSweepResult]]):
    """Apply sweep actions to historical messages."""

    def __init__(self, client: BaseProvider, config: SweepProducerConfig):
        self.client = client
        self.config = config

    def produce(self, result: ResultEnvelope[FiltersSweepResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters sweep failed.")
            return
        total = 0
        for instruction in result.payload.instructions:
            ids = _list_message_ids_shared(
                self.client,
                MessageQueryParams(query=instruction.query, pages=self.config.pages, max_msgs=self.config.max_msgs),
            )
            query_display = instruction.query if instruction.query else _EMPTY_QUERY
            if self.config.dry_run:
                print(
                    f"Query: {query_display} => {len(ids)} messages; "
                    f"+{instruction.add_label_ids} -{instruction.remove_label_ids}"
                )
            else:
                apply_in_chunks(
                    lambda chunk, _inst=instruction: self.client.batch_modify_messages(
                        chunk,
                        add_label_ids=_inst.add_label_ids,
                        remove_label_ids=_inst.remove_label_ids,
                    ),
                    ids,
                    self.config.batch_size,
                )
                print(f"Modified {len(ids)} messages for rule")
            total += len(ids)
        print(f"Sweep complete. Modified {total} messages total.")


class FiltersSweepRangeProducer(Producer[ResultEnvelope[FiltersSweepRangeResult]]):
    """Apply sweep actions across multiple windows."""

    def __init__(self, client: BaseProvider, config: SweepProducerConfig):
        self.client = client
        self.config = config

    def produce(self, result: ResultEnvelope[FiltersSweepRangeResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters sweep-range failed.")
            return
        total = 0
        for window in result.payload.windows:
            print(f"\nWindow: {window.label}")
            window_total = 0
            for instruction in window.instructions:
                ids = _list_message_ids_shared(
                    self.client,
                    MessageQueryParams(query=instruction.query, pages=self.config.pages, max_msgs=self.config.max_msgs),
                )
                if self.config.dry_run:
                    query_display = instruction.query if instruction.query else _EMPTY_QUERY
                    print(
                        f"  {len(ids)} msgs; +{instruction.add_label_ids} "
                        f"-{instruction.remove_label_ids} | {query_display}"
                    )
                else:
                    apply_in_chunks(
                        lambda chunk, _inst=instruction: self.client.batch_modify_messages(
                            chunk,
                            add_label_ids=_inst.add_label_ids,
                            remove_label_ids=_inst.remove_label_ids,
                        ),
                        ids,
                        self.config.batch_size,
                    )
                window_total += len(ids)
            print(f"Window modified: {window_total}")
            total += window_total
        print(f"Total modified across windows: {total}")


class FiltersPruneProducer(Producer[ResultEnvelope[FiltersPruneResult]]):
    """Delete filters that match no messages."""

    def __init__(self, client: BaseProvider, *, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def produce(self, result: ResultEnvelope[FiltersPruneResult]) -> None:
        if not result.ok() or not result.payload:
            print("Filters prune failed.")
            return
        payload = result.payload
        total = len(payload.candidates)
        deleted = 0
        for cand in payload.candidates:
            if not cand.is_empty:
                continue
            fid = cand.filter_obj.get("id")
            query_display = cand.query if cand.query else _EMPTY_QUERY
            if self.dry_run:
                print(f"Would delete filter id={fid} | {query_display}")
            else:
                if self._delete_with_retry(fid):
                    deleted += 1
        print(f"Prune complete. Examined: {total} Deleted: {deleted}")

    def _delete_with_retry(self, fid: str | None) -> bool:
        if not fid:
            return False
        last_err = None
        for attempt in range(3):
            try:
                self.client.delete_filter(fid)
                print(f"Deleted filter id={fid}")
                return True
            except Exception as exc:  # pragma: no cover - retry logging
                last_err = exc
                time.sleep(1.5 * (2 ** attempt))
        print(f"Warning: failed to delete filter id={fid}: {last_err}")
        return False
