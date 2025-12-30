"""Base command executor for Outlook pipeline operations."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Type
    from ..providers.base import BaseMailProvider


class OutlookCommandExecutor:
    """Executes Outlook commands using the consumer-processor-producer pipeline pattern."""

    def __init__(self, consumer_cls: Type, processor_cls: Type, producer_cls: Type):
        """Initialize executor with pipeline component classes.

        Args:
            consumer_cls: Consumer class to instantiate
            processor_cls: Processor class to instantiate
            producer_cls: Producer class to instantiate
        """
        self.consumer_cls = consumer_cls
        self.processor_cls = processor_cls
        self.producer_cls = producer_cls

    def execute(
        self,
        client: BaseMailProvider,
        consumer_kwargs: dict[str, Any] | None = None,
        processor_kwargs: dict[str, Any] | None = None,
        producer_kwargs: dict[str, Any] | None = None,
    ) -> int:
        """Execute the pipeline and return exit code.

        Args:
            client: Outlook API client
            consumer_kwargs: Keyword arguments for consumer
            processor_kwargs: Keyword arguments for processor
            producer_kwargs: Keyword arguments for producer

        Returns:
            Exit code (0 for success, >0 for error)
        """
        consumer = self.consumer_cls(
            client=client,
            **(consumer_kwargs or {})
        )
        processor = self.processor_cls(**(processor_kwargs or {}))
        producer = self.producer_cls(**(producer_kwargs or {}))

        payload = consumer.consume()
        envelope = processor.process(payload)
        producer.produce(envelope)

        return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))
