"""Dataclasses for OTLP telemetry records.

This module provides type-safe data structures for OpenTelemetry Protocol
(OTLP) metrics, events, and spans exported from Claude Code to local JSONL
files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from telemetry.timeutil import nano_to_datetime


@dataclass(frozen=True)
class OTLPValue:
    """A single OTLP value, which may be string, int, double, or bool."""

    string_value: str | None = None
    int_value: int | None = None
    double_value: float | None = None
    bool_value: bool | None = None

    def as_str(self) -> str:
        """Return the value as a string."""
        if self.string_value is not None:
            return self.string_value
        if self.int_value is not None:
            return str(self.int_value)
        if self.double_value is not None:
            return str(self.double_value)
        if self.bool_value is not None:
            return str(self.bool_value)
        return ""

    def as_float(self) -> float:
        """Return the value as a float, coercing from other types if needed."""
        if self.double_value is not None:
            return self.double_value
        if self.int_value is not None:
            return float(self.int_value)
        if self.string_value is not None:
            try:
                return float(self.string_value)
            except (ValueError, TypeError):
                return 0.0
        if self.bool_value is not None:
            return 1.0 if self.bool_value else 0.0
        return 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPValue:
        """Parse an OTLPValue from a dict."""
        return cls(
            string_value=d.get("stringValue"),
            int_value=d.get("intValue"),
            double_value=d.get("doubleValue"),
            bool_value=d.get("boolValue"),
        )


@dataclass(frozen=True)
class OTLPAttribute:
    """A key-value attribute pair."""

    key: str
    value: OTLPValue

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPAttribute:
        """Parse an OTLPAttribute from a dict."""
        value_dict = d.get("value", {})
        return cls(key=d.get("key", ""), value=OTLPValue.from_dict(value_dict))


def _find_attr_str(attrs: list[OTLPAttribute], key: str) -> str | None:
    """Return the string value of the first attribute matching key, or None."""
    for attr in attrs:
        if attr.key == key:
            return attr.value.as_str()
    return None


def _find_attr_float(attrs: list[OTLPAttribute], key: str) -> float | None:
    """Return the float value of the first attribute matching key, or None."""
    for attr in attrs:
        if attr.key == key:
            return attr.value.as_float()
    return None


def _extract_resource_attributes(
    raw_attrs: list[OTLPAttribute],
) -> dict[str, str | None]:
    """Extract well-known resource attributes from OTLP attributes."""
    extracted: dict[str, str | None] = {
        "service_name": "",
        "service_version": "",
        "host_arch": None,
        "os_type": None,
        "os_version": None,
    }

    key_mapping = {
        "service.name": "service_name",
        "service.version": "service_version",
        "host.arch": "host_arch",
        "os.type": "os_type",
        "os.version": "os_version",
    }

    for attr in raw_attrs:
        if attr.key in key_mapping:
            extracted[key_mapping[attr.key]] = attr.value.as_str()

    return extracted


@dataclass(frozen=True)
class OTLPResource:
    """Resource attributes identifying the source of telemetry data."""

    service_name: str
    service_version: str
    host_arch: str | None = None
    os_type: str | None = None
    os_version: str | None = None
    raw_attributes: list[OTLPAttribute] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPResource:
        """Parse an OTLPResource from a dict."""
        attributes = d.get("attributes", [])
        raw_attrs = [OTLPAttribute.from_dict(attr) for attr in attributes]
        extracted = _extract_resource_attributes(raw_attrs)

        return cls(
            service_name=extracted["service_name"] or "",
            service_version=extracted["service_version"] or "",
            host_arch=extracted["host_arch"],
            os_type=extracted["os_type"],
            os_version=extracted["os_version"],
            raw_attributes=raw_attrs,
        )

    def get_attr(self, key: str) -> str | None:
        """Get an attribute value by key."""
        return _find_attr_str(self.raw_attributes, key)


@dataclass(frozen=True)
class MetricDataPoint:
    """A single data point in a metric."""

    start_time_unix_nano: int
    time_unix_nano: int
    value: float
    attributes: list[OTLPAttribute] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        """Convert time_unix_nano to a datetime."""
        return nano_to_datetime(self.time_unix_nano)

    @property
    def start_timestamp(self) -> datetime:
        """Convert start_time_unix_nano to a datetime."""
        return nano_to_datetime(self.start_time_unix_nano)

    def get_attr(self, key: str) -> str | None:
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    def get_attr_as_float(self, key: str) -> float | None:
        """Get an attribute value as float, handling string coercion."""
        return _find_attr_float(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetricDataPoint:
        """Parse a MetricDataPoint from a dict."""
        attributes = d.get("attributes", [])
        return cls(
            start_time_unix_nano=int(d.get("startTimeUnixNano", 0)),
            time_unix_nano=int(d.get("timeUnixNano", 0)),
            value=float(d.get("asDouble", 0.0)),
            attributes=[OTLPAttribute.from_dict(attr) for attr in attributes],
        )


@dataclass(frozen=True)
class OTLPMetric:
    """A single metric with data points.

    Attributes:
        aggregation_temporality: 1 for DELTA, 2 for CUMULATIVE.
    """

    name: str
    description: str
    unit: str
    data_points: list[MetricDataPoint]
    aggregation_temporality: int = 1
    is_monotonic: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPMetric:
        """Parse an OTLPMetric from a dict.

        Real Claude Code metrics are exported as OTLP "sum" points (with
        aggregationTemporality/isMonotonic), not "gauge" points. Prefer
        sum.dataPoints when the "sum" shape is present at all — even with
        an empty dataPoints list — falling back to gauge.dataPoints only
        when there is no "sum" key. Using ``or`` here would wrongly fall
        back to gauge for a valid-but-empty sum metric, since ``[]`` is
        falsy.
        """
        sum_data = d.get("sum")
        gauge = d.get("gauge", {})
        if sum_data is not None:
            data_points = sum_data.get("dataPoints", [])
        else:
            sum_data = {}
            data_points = gauge.get("dataPoints", [])
        agg_tempo = sum_data.get("aggregationTemporality", 1)
        is_mono = sum_data.get("isMonotonic", True)
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            unit=d.get("unit", ""),
            data_points=[MetricDataPoint.from_dict(dp) for dp in data_points],
            aggregation_temporality=agg_tempo,
            is_monotonic=is_mono,
        )


@dataclass
class OTLPMetricsRecord:
    """A complete metrics record from metrics.jsonl."""

    resource: OTLPResource
    scope_name: str
    scope_version: str
    metrics: list[OTLPMetric]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPMetricsRecord:
        """Parse an OTLPMetricsRecord from a dict.

        Handles both OTLP format (with resourceMetrics wrapper) and
        simplified format (direct resource/scopeMetrics). Checks for key
        presence (``is not None``), not truthiness, so an empty
        ``resourceMetrics: []`` wrapper is still treated as OTLP shape
        (yielding an empty record) rather than falling through to the
        simplified-format field names. The inner ``scopeMetrics`` list is
        guarded the same way (``or [{}]``) so an empty-but-present list
        yields an empty scope instead of an IndexError.
        """
        resource_metrics = d.get("resourceMetrics")
        if resource_metrics is not None:
            resource_metric = resource_metrics[0] if resource_metrics else {}
            resource_dict = resource_metric.get("resource", {})
            scope_metrics = resource_metric.get("scopeMetrics") or [{}]
            scope = scope_metrics[0]
        else:
            resource_dict = d.get("resource", {})
            scope_metrics = d.get("scopeMetrics") or [{}]
            scope = scope_metrics[0]

        scope_attrs = scope.get("scope", {})
        metrics_list = scope.get("metrics", [])

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            scope_name=scope_attrs.get("name", ""),
            scope_version=scope_attrs.get("version", ""),
            metrics=[OTLPMetric.from_dict(m) for m in metrics_list],
        )

    def metrics_by_name(self, pattern: str) -> list[OTLPMetric]:
        """Return metrics matching a fnmatch glob pattern."""
        import fnmatch
        return [m for m in self.metrics if fnmatch.fnmatch(m.name, pattern)]

    def earliest_timestamp(self) -> datetime | None:
        """Get the earliest timestamp from all data points."""
        all_times = [dp.timestamp for metric in self.metrics for dp in metric.data_points]
        return min(all_times) if all_times else None



@dataclass(frozen=True)
class OTLPEvent:
    """A single log event from events.jsonl."""

    time_unix_nano: int
    observed_time_unix_nano: int
    body: str
    attributes: list[OTLPAttribute] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        """Convert time_unix_nano to a datetime."""
        return nano_to_datetime(self.time_unix_nano)

    def get_attr(self, key: str) -> str | None:
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    def get_attr_as_float(self, key: str) -> float | None:
        """Get an attribute value as float, handling string coercion."""
        return _find_attr_float(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPEvent:
        """Parse an OTLPEvent from a dict."""
        attributes = d.get("attributes", [])
        body_value = d.get("body", "")
        if isinstance(body_value, dict):
            body_value = body_value.get("stringValue", "")
        return cls(
            time_unix_nano=int(d.get("timeUnixNano", 0)),
            observed_time_unix_nano=int(d.get("observedTimeUnixNano", 0)),
            body=body_value,
            attributes=[OTLPAttribute.from_dict(attr) for attr in attributes],
        )


@dataclass
class OTLPEventsRecord:
    """A complete events record from events.jsonl."""

    resource: OTLPResource
    scope_name: str
    log_records: list[OTLPEvent]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPEventsRecord:
        """Parse an OTLPEventsRecord from a dict.

        Handles both OTLP format (with resourceLogs wrapper) and simplified
        format (direct resource/scopeLogs). The inner ``scopeLogs`` list is
        guarded with ``or [{}]`` so an empty-but-present list yields an empty
        scope instead of an IndexError.
        """
        resource_logs = d.get("resourceLogs")
        if resource_logs is not None:
            resource_log = resource_logs[0] if resource_logs else {}
            resource_dict = resource_log.get("resource", {})
            scope_logs = (resource_log.get("scopeLogs") or [{}])[0]
        else:
            resource_dict = d.get("resource", {})
            scope_logs = (d.get("scopeLogs") or [{}])[0]

        scope_attrs = scope_logs.get("scope", {})
        log_records = scope_logs.get("logRecords", [])

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            scope_name=scope_attrs.get("name", ""),
            log_records=[OTLPEvent.from_dict(event) for event in log_records],
        )


@dataclass(frozen=True)
class OTLPSpan:
    """A single trace span from spans.jsonl."""

    trace_id: str
    span_id: str
    name: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    attributes: list[OTLPAttribute] = field(default_factory=list)

    @property
    def start_timestamp(self) -> datetime:
        """Convert start_time_unix_nano to a datetime."""
        return nano_to_datetime(self.start_time_unix_nano)

    @property
    def duration_ms(self) -> float:
        """Calculate duration in milliseconds."""
        return (self.end_time_unix_nano - self.start_time_unix_nano) / 1e6

    def get_attr(self, key: str) -> str | None:
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPSpan:
        """Parse an OTLPSpan from a dict."""
        attributes = d.get("attributes", [])
        return cls(
            trace_id=d.get("traceId", ""),
            span_id=d.get("spanId", ""),
            name=d.get("name", ""),
            start_time_unix_nano=int(d.get("startTimeUnixNano", 0)),
            end_time_unix_nano=int(d.get("endTimeUnixNano", 0)),
            attributes=[OTLPAttribute.from_dict(attr) for attr in attributes],
        )


@dataclass
class OTLPSpansRecord:
    """A complete spans record from spans.jsonl."""

    resource: OTLPResource
    spans: list[OTLPSpan]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPSpansRecord:
        """Parse an OTLPSpansRecord from a dict.

        Handles both OTLP format (with resourceSpans wrapper) and simplified
        format (direct resource/scopeSpans). Checks for key presence
        (``is not None``), not truthiness, so an empty ``resourceSpans: []``
        wrapper is still treated as OTLP shape (yielding an empty record)
        rather than falling through to the simplified-format field names.
        """
        resource_spans = d.get("resourceSpans")
        if resource_spans is not None:
            resource_span = resource_spans[0] if resource_spans else {}
            resource_dict = resource_span.get("resource", {})
            scope_spans_list = resource_span.get("scopeSpans") or [{}]
            scope_spans = scope_spans_list[0]
        else:
            resource_dict = d.get("resource", {})
            scope_spans_list = d.get("scopeSpans") or [{}]
            scope_spans = scope_spans_list[0]

        spans_list = scope_spans.get("spans", [])

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            spans=[OTLPSpan.from_dict(span) for span in spans_list],
        )


# Backward-compatible re-exports from cost_models
from telemetry.otel.cost_models import (  # noqa: E402, F401
    AnomalyFlag,
    CostMetrics,
    DailyCost,
    ModelCost,
    ModelPerformance,
    PromptMetrics,
    SessionCluster,
    SessionComparison,
    SessionCost,
    SessionHealthScore,
    SessionPerf,
    ToolErrorSummary,
)
