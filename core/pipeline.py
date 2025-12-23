from __future__ import annotations

"""Shared consumer/processor/producer scaffolding."""

from dataclasses import dataclass
from typing import Any, Dict, Generic, List, Optional, Protocol, TypeVar


PayloadT = TypeVar("PayloadT")
ResultT = TypeVar("ResultT")
RequestT = TypeVar("RequestT")


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


class RequestConsumer(Generic[RequestT], Consumer[RequestT]):
    """Generic consumer that wraps any request object.

    Replaces boilerplate consumer classes that all do the same thing:
    store a request and return it on consume().

    Example usage:
        # Instead of defining a separate consumer class:
        request = SomeRequest(...)
        consumer = RequestConsumer(request)
        payload = consumer.consume()  # Returns the request
    """

    def __init__(self, request: RequestT) -> None:
        self._request = request

    def consume(self) -> RequestT:  # pragma: no cover - trivial
        return self._request


class BaseProducer:
    """Base class for pipeline producers with common error handling.

    Provides a template method pattern: subclasses override _produce_success()
    to handle successful results while error handling is centralized here.

    Example usage:
        class MyProducer(BaseProducer):
            def _produce_success(self, payload: MyResult, diagnostics: Optional[dict]) -> None:
                print(f"Success: {payload.message}")
    """

    def produce(self, result: ResultEnvelope) -> None:
        """Template method: handle errors, delegate success to subclass."""
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        if result.payload is not None:
            self._produce_success(result.payload, result.diagnostics)

    def _produce_success(self, payload: Any, diagnostics: Optional[Dict[str, Any]]) -> None:
        """Override in subclass to handle successful result output."""
        raise NotImplementedError("Subclass must implement _produce_success")

    @staticmethod
    def print_error(result: ResultEnvelope) -> bool:
        """Print error message if result failed. Returns True if error was printed."""
        if result.ok():
            return False
        msg = (result.diagnostics or {}).get("message")
        if msg:
            print(msg)
        return True

    @staticmethod
    def print_logs(logs: List[str]) -> None:
        """Print a list of log messages."""
        for line in logs:
            print(line)
