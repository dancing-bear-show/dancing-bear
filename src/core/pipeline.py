"""Shared consumer/processor/producer scaffolding."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Generic, List, Optional, Protocol, TypeVar


PayloadT = TypeVar("PayloadT")
ResultT = TypeVar("ResultT")
RequestT = TypeVar("RequestT")
T = TypeVar("T")
R = TypeVar("R")


@dataclass
class ResultEnvelope(Generic[ResultT]):
    status: str
    payload: Optional[ResultT] = None
    diagnostics: Optional[dict[str, Any]] = None

    def ok(self) -> bool:
        return self.status.lower() == "success"

    def unwrap(self) -> ResultT:
        """Return payload or raise ValueError. Use after ok() check."""
        if self.payload is None:
            msg = (self.diagnostics or {}).get("message", "No payload")
            raise ValueError(msg)
        return self.payload


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


class SafeProcessor(Generic[T, R]):
    """Base processor with automatic error handling wrapper.

    Provides a template method pattern: subclasses override _process_safe()
    to implement processing logic without manual error handling.

    Example usage:
        class MyProcessor(SafeProcessor[Request, Result]):
            def _process_safe(self, payload: Request) -> Result:
                # Implementation that may raise exceptions
                return Result(...)
    """

    def process(self, payload: T) -> ResultEnvelope[R]:
        """Wrap _process_safe with error handling."""
        try:
            result = self._process_safe(payload)
            return ResultEnvelope(status="success", payload=result)
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})

    def _process_safe(self, payload: T) -> R:
        """Override to implement processing logic without error handling boilerplate."""
        raise NotImplementedError("Subclass must implement _process_safe")


def run_pipeline(request: Any, processor_cls: type, producer_cls: type) -> int:
    """Execute a pipeline and return CLI exit code.

    Simplifies command handlers by encapsulating the common pattern:
    1. Process the request
    2. Produce output
    3. Return appropriate exit code

    Args:
        request: The request object to process
        processor_cls: Processor class (instantiated with no args)
        producer_cls: Producer class (instantiated with no args)

    Returns:
        0 on success, or error code from diagnostics (default 2)

    Example:
        def run_outlook_xyz(args) -> int:
            svc = _build_outlook_service(args)
            if not svc:
                return 1
            request = XyzRequest(service=svc, ...)
            return run_pipeline(request, XyzProcessor, XyzProducer)
    """
    envelope = processor_cls().process(request)
    producer_cls().produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 2))
