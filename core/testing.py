from __future__ import annotations

"""Testing helpers for consumers/processors/producers."""

from dataclasses import dataclass
from typing import Any, Callable

from .pipeline import Consumer, Processor, Producer


@dataclass
class StubConsumer(Consumer[Any]):
    payload: Any

    def consume(self) -> Any:  # pragma: no cover - trivial
        return self.payload


@dataclass
class StubProcessor(Processor[Any, Any]):
    fn: Callable[[Any], Any]

    def process(self, payload: Any) -> Any:  # pragma: no cover - trivial
        return self.fn(payload)


@dataclass
class CaptureProducer(Producer[Any]):
    sink: list[Any]

    def produce(self, result: Any) -> None:  # pragma: no cover - trivial
        self.sink.append(result)
