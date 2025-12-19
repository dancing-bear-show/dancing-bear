from __future__ import annotations

"""Shared consumer/processor/producer scaffolding."""

from dataclasses import dataclass
from typing import Any, Generic, Optional, Protocol, TypeVar


PayloadT = TypeVar("PayloadT")
ResultT = TypeVar("ResultT")


@dataclass
class ResultEnvelope(Generic[ResultT]):
    status: str
    payload: Optional[ResultT] = None
    diagnostics: Optional[dict[str, Any]] = None

    def ok(self) -> bool:
        return self.status.lower() == "success"


class Consumer(Protocol[PayloadT]):
    def consume(self) -> PayloadT:
        ...


class Processor(Protocol[PayloadT, ResultT]):
    def process(self, payload: PayloadT) -> ResultT:
        ...


class Producer(Protocol[ResultT]):
    def produce(self, result: ResultT) -> None:
        ...
