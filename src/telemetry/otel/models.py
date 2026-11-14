"""Dataclasses for OTLP telemetry records.

This module provides type-safe data structures for OpenTelemetry Protocol
(OTLP) metrics, events, and spans exported from Claude Code to local JSONL
files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from telemetry.otel.otlp_walk import (
    RECORD_EXCEPTIONS,
    attr_key,
    iter_dicts,
    metric_series,
    parse_unix_nano,
    require_unix_nano,
    select_datapoint_value,
)
from telemetry.timeutil import nano_to_datetime


def _first_scope(
    d: dict[str, Any], wrapper_key: str, scope_key: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(resource_dict, first_scope_dict)`` for an OTLP or simplified record.

    Handles both OTLP format (``wrapper_key`` such as ``resourceMetrics``
    wrapping ``resource``/``scope_key``) and simplified format (those keys at
    top level). The wrapper is checked for presence, not truthiness, so an
    empty ``resourceX: []`` is still OTLP shape (an empty record). Null or
    wrongly-typed values at any level yield ``{}`` instead of raising.
    """
    wrapper = d.get(wrapper_key)
    container = next(iter_dicts(wrapper), {}) if wrapper is not None else d
    resource_raw = container.get("resource")
    resource_dict = resource_raw if isinstance(resource_raw, dict) else {}
    return resource_dict, next(iter_dicts(container.get(scope_key)), {})


def _dict_or_empty(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_from_dicts(cls: Any, items: object) -> list[Any]:
    """Return ``cls.from_dict(item)`` for each dict in *items*, skipping any that raise.

    One malformed sibling (e.g. a logRecord with an unusable timestamp) must
    not drop the whole envelope.
    """
    result = []
    for item in iter_dicts(items):
        try:
            result.append(cls.from_dict(item))
        except RECORD_EXCEPTIONS:
            continue
    return result


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
        """Parse an OTLPAttribute from a dict.

        A non-string key (``[]``, ``null``) becomes ``""`` so a lookup by key
        cannot raise ``TypeError`` and drop the surrounding record.
        """
        return cls(
            key=attr_key(d.get("key")) or "",
            value=OTLPValue.from_dict(_dict_or_empty(d.get("value"))),
        )


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

    service_name: str  # noqa
    service_version: str  # noqa
    host_arch: str | None = None  # noqa
    os_type: str | None = None  # noqa
    os_version: str | None = None  # noqa
    raw_attributes: list[OTLPAttribute] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPResource:
        """Parse an OTLPResource from a dict."""
        raw_attrs = [OTLPAttribute.from_dict(attr) for attr in iter_dicts(d.get("attributes"))]
        extracted = _extract_resource_attributes(raw_attrs)

        return cls(
            service_name=extracted["service_name"] or "",
            service_version=extracted["service_version"] or "",
            host_arch=extracted["host_arch"],
            os_type=extracted["os_type"],
            os_version=extracted["os_version"],
            raw_attributes=raw_attrs,
        )

    def get_attr(self, key: str) -> str | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
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

    @property  # noqa - called via src/telemetry/otel/retention.py, cli/inspect.py, tests/telemetry_tests/test_otel_models.py
    def start_timestamp(self) -> datetime:
        """Convert start_time_unix_nano to a datetime."""
        return nano_to_datetime(self.start_time_unix_nano)

    def get_attr(self, key: str) -> str | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    def get_attr_as_float(self, key: str) -> float | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
        """Get an attribute value as float, handling string coercion."""
        return _find_attr_float(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MetricDataPoint:
        """Parse a MetricDataPoint from a dict.

        The value is ``asDouble``, else ``asInt`` (integer points carry only
        that). An unusable ``timeUnixNano`` raises ``ValueError``.
        """
        return cls(
            start_time_unix_nano=parse_unix_nano(d.get("startTimeUnixNano")) or 0,
            time_unix_nano=require_unix_nano(d.get("timeUnixNano", 0)),
            value=select_datapoint_value(d),
            attributes=[OTLPAttribute.from_dict(attr) for attr in iter_dicts(d.get("attributes"))],
        )


@dataclass(frozen=True)
class OTLPMetric:
    """A single metric with data points.

    Attributes:
        aggregation_temporality: 1 for DELTA, 2 for CUMULATIVE.
    """

    name: str
    description: str  # noqa
    unit: str  # noqa
    data_points: list[MetricDataPoint]
    aggregation_temporality: int = 1  # noqa
    is_monotonic: bool = True  # noqa

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPMetric:
        """Parse an OTLPMetric from a dict.

        Real Claude Code metrics are exported as OTLP "sum" points (with
        aggregationTemporality/isMonotonic), not "gauge" points; see
        ``otlp_walk.metric_series`` for the selection rule. A data point that
        fails to parse is skipped, not the whole metric.
        """
        shape, data_points = metric_series(d)
        agg_tempo = shape.get("aggregationTemporality", 1)
        is_mono = shape.get("isMonotonic", True)
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            unit=d.get("unit", ""),
            data_points=_safe_from_dicts(MetricDataPoint, data_points),
            aggregation_temporality=agg_tempo,
            is_monotonic=is_mono,
        )


@dataclass
class OTLPMetricsRecord:
    """A complete metrics record from metrics.jsonl."""

    resource: OTLPResource  # noqa
    scope_name: str  # noqa
    scope_version: str  # noqa
    metrics: list[OTLPMetric]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPMetricsRecord:
        """Parse an OTLPMetricsRecord from a dict.

        Handles both OTLP format (with resourceMetrics wrapper) and
        simplified format (direct resource/scopeMetrics). Checks for key
        presence (``is not None``), not truthiness, so an empty
        ``resourceMetrics: []`` wrapper is still treated as OTLP shape
        (yielding an empty record) rather than falling through to the
        simplified-format field names. Malformed nesting yields an empty
        scope, and a metric that fails to parse is skipped.
        """
        resource_dict, scope = _first_scope(d, "resourceMetrics", "scopeMetrics")
        scope_attrs = _dict_or_empty(scope.get("scope"))

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            scope_name=scope_attrs.get("name", ""),
            scope_version=scope_attrs.get("version", ""),
            metrics=_safe_from_dicts(OTLPMetric, scope.get("metrics")),
        )

    def metrics_by_name(self, pattern: str) -> list[OTLPMetric]:  # noqa - called via src/telemetry/otel/cli/query.py:80
        """Return metrics matching a fnmatch glob pattern."""
        import fnmatch
        return [m for m in self.metrics if fnmatch.fnmatch(m.name, pattern)]

    def earliest_timestamp(self) -> datetime | None:  # noqa - called via src/telemetry/otel/retention.py:171, cli/inspect.py:69
        """Get the earliest timestamp from all data points."""
        all_times = [dp.timestamp for metric in self.metrics for dp in metric.data_points]
        return min(all_times) if all_times else None



@dataclass(frozen=True)
class OTLPEvent:
    """A single log event from events.jsonl."""

    time_unix_nano: int
    observed_time_unix_nano: int  # noqa
    body: str  # noqa
    attributes: list[OTLPAttribute] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        """Convert time_unix_nano to a datetime."""
        return nano_to_datetime(self.time_unix_nano)

    def get_attr(self, key: str) -> str | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    def get_attr_as_float(self, key: str) -> float | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
        """Get an attribute value as float, handling string coercion."""
        return _find_attr_float(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPEvent:
        """Parse an OTLPEvent from a dict; an unusable ``timeUnixNano`` raises ``ValueError``."""
        body_value = d.get("body", "")
        if isinstance(body_value, dict):
            body_value = body_value.get("stringValue", "")
        return cls(
            time_unix_nano=require_unix_nano(d.get("timeUnixNano", 0)),
            observed_time_unix_nano=parse_unix_nano(d.get("observedTimeUnixNano")) or 0,
            body=body_value,
            attributes=[OTLPAttribute.from_dict(attr) for attr in iter_dicts(d.get("attributes"))],
        )


@dataclass
class OTLPEventsRecord:
    """A complete events record from events.jsonl."""

    resource: OTLPResource  # noqa
    scope_name: str  # noqa
    log_records: list[OTLPEvent]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPEventsRecord:
        """Parse an OTLPEventsRecord from a dict.

        Handles both OTLP format (with resourceLogs wrapper) and simplified
        format (direct resource/scopeLogs). Malformed nesting yields an empty
        scope, and a log record that fails to parse is skipped.
        """
        resource_dict, scope_logs = _first_scope(d, "resourceLogs", "scopeLogs")
        scope_attrs = _dict_or_empty(scope_logs.get("scope"))

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            scope_name=scope_attrs.get("name", ""),
            log_records=_safe_from_dicts(OTLPEvent, scope_logs.get("logRecords")),
        )


@dataclass(frozen=True)
class OTLPSpan:
    """A single trace span from spans.jsonl."""

    trace_id: str  # noqa
    span_id: str  # noqa
    name: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    attributes: list[OTLPAttribute] = field(default_factory=list)

    @property  # noqa - called via src/telemetry/otel/retention.py, cli/inspect.py, tests/telemetry_tests/test_otel_models.py
    def start_timestamp(self) -> datetime:
        """Convert start_time_unix_nano to a datetime."""
        return nano_to_datetime(self.start_time_unix_nano)

    @property  # noqa - called via tests/telemetry_tests/test_otel_models.py:763 (self.span.duration_ms)
    def duration_ms(self) -> float:
        """Calculate duration in milliseconds."""
        return (self.end_time_unix_nano - self.start_time_unix_nano) / 1e6

    def get_attr(self, key: str) -> str | None:  # noqa - called via src/telemetry/otel/cli/, src/telemetry/otel/analytics/, tests/telemetry_tests/test_otel_models.py
        """Get an attribute value by key."""
        return _find_attr_str(self.attributes, key)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPSpan:
        """Parse an OTLPSpan from a dict; an unusable timestamp raises ``ValueError``."""
        return cls(
            trace_id=d.get("traceId", ""),
            span_id=d.get("spanId", ""),
            name=d.get("name", ""),
            start_time_unix_nano=require_unix_nano(d.get("startTimeUnixNano", 0)),
            end_time_unix_nano=require_unix_nano(d.get("endTimeUnixNano", 0)),
            attributes=[OTLPAttribute.from_dict(attr) for attr in iter_dicts(d.get("attributes"))],
        )


@dataclass
class OTLPSpansRecord:
    """A complete spans record from spans.jsonl."""

    resource: OTLPResource  # noqa
    spans: list[OTLPSpan]  # noqa

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OTLPSpansRecord:
        """Parse an OTLPSpansRecord from a dict.

        Handles both OTLP format (with resourceSpans wrapper) and simplified
        format (direct resource/scopeSpans). Checks for key presence
        (``is not None``), not truthiness, so an empty ``resourceSpans: []``
        wrapper is still treated as OTLP shape (yielding an empty record)
        rather than falling through to the simplified-format field names. A
        span that fails to parse is skipped.
        """
        resource_dict, scope_spans = _first_scope(d, "resourceSpans", "scopeSpans")

        return cls(
            resource=OTLPResource.from_dict(resource_dict),
            spans=_safe_from_dicts(OTLPSpan, scope_spans.get("spans")),
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
