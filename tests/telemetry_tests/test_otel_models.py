"""Tests for telemetry/otel/models.py OTLP dataclasses."""

import unittest
from datetime import datetime, timezone

from telemetry.otel.models import (
    MetricDataPoint,
    OTLPAttribute,
    OTLPEvent,
    OTLPEventsRecord,
    OTLPMetric,
    OTLPMetricsRecord,
    OTLPResource,
    OTLPSpan,
    OTLPSpansRecord,
    OTLPValue,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers — plain functions that always return a fresh dict so
# tests that mutate dicts cannot pollute each other.
# ---------------------------------------------------------------------------

def _attr_dict(key: str, **value_fields) -> dict:
    """Build a raw OTLP attribute dict."""
    return {"key": key, "value": value_fields}


def _resource_dict(*attrs) -> dict:
    """Build a raw OTLP resource dict with the given attribute dicts."""
    return {"attributes": list(attrs)}


def _full_resource_dict() -> dict:
    return _resource_dict(
        _attr_dict("service.name", stringValue="my-service"),
        _attr_dict("service.version", stringValue="1.2.3"),
        _attr_dict("host.arch", stringValue="arm64"),
        _attr_dict("os.type", stringValue="darwin"),
        _attr_dict("os.version", stringValue="24.0.0"),
    )


def _datapoint_dict(
    value: float = 42.0,
    time_ns: int = 1_700_000_000_000_000_000,
    start_ns: int = 1_699_000_000_000_000_000,
    attrs=None,
) -> dict:
    d: dict = {
        "asDouble": value,
        "timeUnixNano": time_ns,
        "startTimeUnixNano": start_ns,
    }
    if attrs:
        d["attributes"] = attrs
    return d


def _sum_metric_dict(name: str = "my.metric", data_points=None) -> dict:
    dps = data_points if data_points is not None else [_datapoint_dict()]
    return {
        "name": name,
        "description": "A test metric",
        "unit": "By",
        "sum": {
            "dataPoints": dps,
            "aggregationTemporality": 2,
            "isMonotonic": True,
        },
    }


def _gauge_metric_dict(name: str = "my.gauge") -> dict:
    return {
        "name": name,
        "description": "A gauge metric",
        "unit": "1",
        "gauge": {
            "dataPoints": [_datapoint_dict(value=7.0)],
        },
    }


# ---------------------------------------------------------------------------
# OTLPValue
# ---------------------------------------------------------------------------

class TestOTLPValueAsStr(unittest.TestCase):

    def test_string_value(self):
        v = OTLPValue(string_value="hello")
        self.assertEqual(v.as_str(), "hello")

    def test_int_value(self):
        v = OTLPValue(int_value=42)
        self.assertEqual(v.as_str(), "42")

    def test_double_value(self):
        v = OTLPValue(double_value=3.14)
        self.assertEqual(v.as_str(), "3.14")

    def test_bool_value_true(self):
        v = OTLPValue(bool_value=True)
        self.assertEqual(v.as_str(), "True")

    def test_bool_value_false(self):
        v = OTLPValue(bool_value=False)
        self.assertEqual(v.as_str(), "False")

    def test_all_none_returns_empty_string(self):
        v = OTLPValue()
        self.assertEqual(v.as_str(), "")

    def test_string_takes_priority_over_int(self):
        # string_value is checked first
        v = OTLPValue(string_value="hi", int_value=99)
        self.assertEqual(v.as_str(), "hi")


class TestOTLPValueAsFloat(unittest.TestCase):

    def test_double_value(self):
        v = OTLPValue(double_value=2.5)
        self.assertAlmostEqual(v.as_float(), 2.5)

    def test_int_value(self):
        v = OTLPValue(int_value=10)
        self.assertAlmostEqual(v.as_float(), 10.0)

    def test_numeric_string_value(self):
        v = OTLPValue(string_value="3.14")
        self.assertAlmostEqual(v.as_float(), 3.14)

    def test_non_numeric_string_returns_zero(self):
        """The except (ValueError, TypeError) fallback must return 0.0."""
        v = OTLPValue(string_value="not-a-number")
        self.assertAlmostEqual(v.as_float(), 0.0)

    def test_bool_value_true(self):
        v = OTLPValue(bool_value=True)
        self.assertAlmostEqual(v.as_float(), 1.0)

    def test_bool_value_false(self):
        v = OTLPValue(bool_value=False)
        self.assertAlmostEqual(v.as_float(), 0.0)

    def test_all_none_returns_zero(self):
        v = OTLPValue()
        self.assertAlmostEqual(v.as_float(), 0.0)

    def test_double_takes_priority_over_int(self):
        v = OTLPValue(double_value=1.5, int_value=99)
        self.assertAlmostEqual(v.as_float(), 1.5)


class TestOTLPValueFromDict(unittest.TestCase):

    def test_string_value(self):
        v = OTLPValue.from_dict({"stringValue": "foo"})
        self.assertEqual(v.string_value, "foo")
        self.assertIsNone(v.int_value)
        self.assertIsNone(v.double_value)
        self.assertIsNone(v.bool_value)

    def test_int_value(self):
        v = OTLPValue.from_dict({"intValue": 7})
        self.assertEqual(v.int_value, 7)

    def test_double_value(self):
        v = OTLPValue.from_dict({"doubleValue": 1.23})
        self.assertAlmostEqual(v.double_value, 1.23)

    def test_bool_value(self):
        v = OTLPValue.from_dict({"boolValue": True})
        self.assertTrue(v.bool_value)

    def test_empty_dict_gives_all_none(self):
        v = OTLPValue.from_dict({})
        self.assertIsNone(v.string_value)
        self.assertIsNone(v.int_value)
        self.assertIsNone(v.double_value)
        self.assertIsNone(v.bool_value)


# ---------------------------------------------------------------------------
# OTLPAttribute
# ---------------------------------------------------------------------------

class TestOTLPAttributeFromDict(unittest.TestCase):

    def test_key_and_string_value(self):
        a = OTLPAttribute.from_dict({"key": "my.key", "value": {"stringValue": "bar"}})
        self.assertEqual(a.key, "my.key")
        self.assertEqual(a.value.string_value, "bar")

    def test_missing_key_defaults_to_empty(self):
        a = OTLPAttribute.from_dict({"value": {"intValue": 5}})
        self.assertEqual(a.key, "")
        self.assertEqual(a.value.int_value, 5)

    def test_missing_value_gives_empty_otlp_value(self):
        a = OTLPAttribute.from_dict({"key": "k"})
        self.assertIsNone(a.value.string_value)
        self.assertIsNone(a.value.int_value)


# ---------------------------------------------------------------------------
# OTLPResource
# ---------------------------------------------------------------------------

class TestOTLPResourceFromDict(unittest.TestCase):

    def test_all_known_attributes_extracted(self):
        r = OTLPResource.from_dict(_full_resource_dict())
        self.assertEqual(r.service_name, "my-service")
        self.assertEqual(r.service_version, "1.2.3")
        self.assertEqual(r.host_arch, "arm64")
        self.assertEqual(r.os_type, "darwin")
        self.assertEqual(r.os_version, "24.0.0")

    def test_missing_optional_attributes_are_none(self):
        r = OTLPResource.from_dict(
            _resource_dict(_attr_dict("service.name", stringValue="svc"))
        )
        self.assertEqual(r.service_name, "svc")
        self.assertIsNone(r.host_arch)
        self.assertIsNone(r.os_type)
        self.assertIsNone(r.os_version)

    def test_empty_attributes_list(self):
        r = OTLPResource.from_dict({"attributes": []})
        self.assertEqual(r.service_name, "")
        self.assertEqual(r.service_version, "")

    def test_missing_attributes_key(self):
        r = OTLPResource.from_dict({})
        self.assertEqual(r.service_name, "")

    def test_raw_attributes_preserved(self):
        r = OTLPResource.from_dict(_full_resource_dict())
        self.assertEqual(len(r.raw_attributes), 5)


class TestOTLPResourceGetAttr(unittest.TestCase):

    def setUp(self):
        self.resource = OTLPResource.from_dict(
            _resource_dict(_attr_dict("service.name", stringValue="test-svc"))
        )

    def test_get_attr_found(self):
        self.assertEqual(self.resource.get_attr("service.name"), "test-svc")

    def test_get_attr_not_found(self):
        self.assertIsNone(self.resource.get_attr("nonexistent.key"))


# ---------------------------------------------------------------------------
# MetricDataPoint
# ---------------------------------------------------------------------------

# Use a fixed nanosecond timestamp that maps to a known UTC time.
# 1700000000 seconds = 2023-11-14T22:13:20Z
_TIME_NS = 1_700_000_000_000_000_000
_START_NS = 1_699_900_000_000_000_000


class TestMetricDataPointFromDict(unittest.TestCase):

    def test_basic_parse(self):
        dp = MetricDataPoint.from_dict(_datapoint_dict(value=5.5, time_ns=_TIME_NS, start_ns=_START_NS))
        self.assertAlmostEqual(dp.value, 5.5)
        self.assertEqual(dp.time_unix_nano, _TIME_NS)
        self.assertEqual(dp.start_time_unix_nano, _START_NS)

    def test_attributes_parsed(self):
        dp = MetricDataPoint.from_dict(
            _datapoint_dict(attrs=[_attr_dict("env", stringValue="prod")])
        )
        self.assertEqual(len(dp.attributes), 1)
        self.assertEqual(dp.attributes[0].key, "env")

    def test_defaults_when_fields_missing(self):
        dp = MetricDataPoint.from_dict({})
        self.assertAlmostEqual(dp.value, 0.0)
        self.assertEqual(dp.time_unix_nano, 0)
        self.assertEqual(dp.start_time_unix_nano, 0)


class TestMetricDataPointTimestampProperties(unittest.TestCase):

    def setUp(self):
        self.dp = MetricDataPoint.from_dict(
            _datapoint_dict(time_ns=_TIME_NS, start_ns=_START_NS)
        )

    def test_timestamp_is_datetime(self):
        self.assertIsInstance(self.dp.timestamp, datetime)

    def test_timestamp_is_utc(self):
        self.assertEqual(self.dp.timestamp.tzinfo, timezone.utc)

    def test_start_timestamp_is_datetime(self):
        self.assertIsInstance(self.dp.start_timestamp, datetime)

    def test_start_timestamp_is_utc(self):
        self.assertEqual(self.dp.start_timestamp.tzinfo, timezone.utc)

    def test_timestamp_before_start_timestamp(self):
        # _TIME_NS > _START_NS so timestamp should be later
        self.assertGreater(self.dp.timestamp, self.dp.start_timestamp)


class TestMetricDataPointGetAttr(unittest.TestCase):

    def setUp(self):
        self.dp = MetricDataPoint.from_dict(
            _datapoint_dict(attrs=[
                _attr_dict("region", stringValue="us-east-1"),
                _attr_dict("cost", doubleValue=1.5),
            ])
        )

    def test_get_attr_found(self):
        self.assertEqual(self.dp.get_attr("region"), "us-east-1")

    def test_get_attr_not_found(self):
        self.assertIsNone(self.dp.get_attr("missing"))

    def test_get_attr_as_float_found(self):
        self.assertAlmostEqual(self.dp.get_attr_as_float("cost"), 1.5)

    def test_get_attr_as_float_not_found(self):
        self.assertIsNone(self.dp.get_attr_as_float("missing"))


# ---------------------------------------------------------------------------
# OTLPMetric
# ---------------------------------------------------------------------------

class TestOTLPMetricFromDict(unittest.TestCase):

    def test_sum_with_data_points(self):
        """Happy path: sum present with populated dataPoints."""
        m = OTLPMetric.from_dict(_sum_metric_dict())
        self.assertEqual(m.name, "my.metric")
        self.assertEqual(m.unit, "By")
        self.assertEqual(len(m.data_points), 1)
        self.assertAlmostEqual(m.data_points[0].value, 42.0)
        self.assertEqual(m.aggregation_temporality, 2)
        self.assertTrue(m.is_monotonic)

    def test_sum_present_but_empty_data_points_uses_sum_not_gauge(self):
        """Critical edge case: sum key present with empty dataPoints must NOT fall back to gauge.

        Using ``or`` instead of ``is not None`` would wrongly pick up gauge here.
        """
        d = {
            "name": "empty.sum",
            "description": "",
            "unit": "1",
            "sum": {
                "dataPoints": [],          # empty — but sum IS present
                "aggregationTemporality": 2,
                "isMonotonic": True,
            },
            "gauge": {
                "dataPoints": [_datapoint_dict(value=999.0)],  # must be ignored
            },
        }
        m = OTLPMetric.from_dict(d)
        # data_points must be empty because we respected sum, not gauge
        self.assertEqual(len(m.data_points), 0)
        # aggregation_temporality came from sum, not the default 1
        self.assertEqual(m.aggregation_temporality, 2)

    def test_sum_absent_falls_back_to_gauge(self):
        """When there is no sum key at all, use gauge.dataPoints."""
        m = OTLPMetric.from_dict(_gauge_metric_dict())
        self.assertEqual(m.name, "my.gauge")
        self.assertEqual(len(m.data_points), 1)
        self.assertAlmostEqual(m.data_points[0].value, 7.0)
        # No sum: aggregation_temporality and is_monotonic keep defaults
        self.assertEqual(m.aggregation_temporality, 1)
        self.assertTrue(m.is_monotonic)

    def test_defaults_when_minimal_dict(self):
        m = OTLPMetric.from_dict({"name": "x"})
        self.assertEqual(m.name, "x")
        self.assertEqual(m.description, "")
        self.assertEqual(m.unit, "")
        self.assertEqual(m.data_points, [])


# ---------------------------------------------------------------------------
# OTLPMetricsRecord
# ---------------------------------------------------------------------------

def _otlp_metrics_wrapper(service_name: str = "svc", metrics=None) -> dict:
    """Build a full OTLP resourceMetrics wrapper dict."""
    if metrics is None:
        metrics = [_sum_metric_dict()]
    return {
        "resourceMetrics": [
            {
                "resource": _resource_dict(
                    _attr_dict("service.name", stringValue=service_name)
                ),
                "scopeMetrics": [
                    {
                        "scope": {"name": "my.scope", "version": "0.1"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def _simplified_metrics_dict(service_name: str = "svc", metrics=None) -> dict:
    """Build a simplified (non-wrapper) metrics record dict."""
    metrics = metrics or [_sum_metric_dict()]
    return {
        "resource": _resource_dict(
            _attr_dict("service.name", stringValue=service_name)
        ),
        "scopeMetrics": [
            {
                "scope": {"name": "simple.scope", "version": "0.2"},
                "metrics": metrics,
            }
        ],
    }


class TestOTLPMetricsRecordFromDict(unittest.TestCase):

    def test_otlp_wrapper_format(self):
        rec = OTLPMetricsRecord.from_dict(_otlp_metrics_wrapper())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(rec.scope_name, "my.scope")
        self.assertEqual(rec.scope_version, "0.1")
        self.assertEqual(len(rec.metrics), 1)

    def test_otlp_wrapper_empty_resource_metrics_list(self):
        """Empty resourceMetrics list: OTLP shape detected, empty record produced — no IndexError."""
        rec = OTLPMetricsRecord.from_dict({"resourceMetrics": []})
        self.assertEqual(rec.metrics, [])
        self.assertEqual(rec.scope_name, "")

    def test_simplified_format(self):
        rec = OTLPMetricsRecord.from_dict(_simplified_metrics_dict())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(rec.scope_name, "simple.scope")
        self.assertEqual(rec.scope_version, "0.2")
        self.assertEqual(len(rec.metrics), 1)

    def test_empty_dict_gives_empty_record(self):
        rec = OTLPMetricsRecord.from_dict({})
        self.assertEqual(rec.metrics, [])
        self.assertEqual(rec.scope_name, "")


class TestOTLPMetricsRecordMetricsByName(unittest.TestCase):

    def setUp(self):
        metrics = [
            _sum_metric_dict(name="app.cpu.usage"),
            _sum_metric_dict(name="app.mem.usage"),
            _sum_metric_dict(name="http.requests"),
        ]
        self.rec = OTLPMetricsRecord.from_dict(_otlp_metrics_wrapper(metrics=metrics))

    def test_exact_name_match(self):
        found = self.rec.metrics_by_name("http.requests")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "http.requests")

    def test_glob_prefix(self):
        found = self.rec.metrics_by_name("app.*")
        self.assertEqual(len(found), 2)

    def test_no_match_returns_empty_list(self):
        found = self.rec.metrics_by_name("nonexistent.*")
        self.assertEqual(found, [])


class TestOTLPMetricsRecordEarliestTimestamp(unittest.TestCase):

    def test_returns_earliest(self):
        earlier_ns = 1_699_000_000_000_000_000
        later_ns = 1_700_000_000_000_000_000
        metrics = [
            _sum_metric_dict(name="a", data_points=[_datapoint_dict(time_ns=later_ns)]),
            _sum_metric_dict(name="b", data_points=[_datapoint_dict(time_ns=earlier_ns)]),
        ]
        rec = OTLPMetricsRecord.from_dict(_otlp_metrics_wrapper(metrics=metrics))
        ts = rec.earliest_timestamp()
        self.assertIsNotNone(ts)
        self.assertIsInstance(ts, datetime)
        # Should be the earlier timestamp
        from telemetry.timeutil import nano_to_datetime
        self.assertEqual(ts, nano_to_datetime(earlier_ns))

    def test_no_data_points_returns_none(self):
        metrics = [_sum_metric_dict(name="empty", data_points=[])]
        rec = OTLPMetricsRecord.from_dict(_otlp_metrics_wrapper(metrics=metrics))
        self.assertIsNone(rec.earliest_timestamp())

    def test_no_metrics_returns_none(self):
        rec = OTLPMetricsRecord.from_dict(_otlp_metrics_wrapper(metrics=[]))
        self.assertIsNone(rec.earliest_timestamp())


# ---------------------------------------------------------------------------
# OTLPEvent
# ---------------------------------------------------------------------------

_EVENT_NS = 1_700_000_000_000_000_000


def _event_dict_plain_body(body: str = "hello event") -> dict:
    return {
        "timeUnixNano": _EVENT_NS,
        "observedTimeUnixNano": _EVENT_NS + 1000,
        "body": body,
        "attributes": [_attr_dict("level", stringValue="INFO")],
    }


def _event_dict_wrapped_body(string_value: str = "wrapped body") -> dict:
    return {
        "timeUnixNano": _EVENT_NS,
        "observedTimeUnixNano": _EVENT_NS + 500,
        "body": {"stringValue": string_value},
        "attributes": [],
    }


class TestOTLPEventFromDict(unittest.TestCase):

    def test_plain_string_body(self):
        e = OTLPEvent.from_dict(_event_dict_plain_body("my message"))
        self.assertEqual(e.body, "my message")

    def test_dict_body_extracts_string_value(self):
        """body as dict with stringValue key must extract the inner string."""
        e = OTLPEvent.from_dict(_event_dict_wrapped_body("inner text"))
        self.assertEqual(e.body, "inner text")

    def test_dict_body_missing_string_value_gives_empty(self):
        e = OTLPEvent.from_dict({
            "timeUnixNano": _EVENT_NS,
            "observedTimeUnixNano": _EVENT_NS,
            "body": {"otherKey": "ignored"},
        })
        self.assertEqual(e.body, "")

    def test_time_unix_nano_set(self):
        e = OTLPEvent.from_dict(_event_dict_plain_body())
        self.assertEqual(e.time_unix_nano, _EVENT_NS)

    def test_attributes_parsed(self):
        e = OTLPEvent.from_dict(_event_dict_plain_body())
        self.assertEqual(len(e.attributes), 1)
        self.assertEqual(e.attributes[0].key, "level")

    def test_defaults_when_fields_missing(self):
        e = OTLPEvent.from_dict({})
        self.assertEqual(e.time_unix_nano, 0)
        self.assertEqual(e.observed_time_unix_nano, 0)
        self.assertEqual(e.body, "")
        self.assertEqual(e.attributes, [])


class TestOTLPEventTimestampAndGetAttr(unittest.TestCase):

    def setUp(self):
        self.event = OTLPEvent.from_dict({
            "timeUnixNano": _EVENT_NS,
            "observedTimeUnixNano": _EVENT_NS,
            "body": "test",
            "attributes": [
                _attr_dict("severity", stringValue="WARN"),
                _attr_dict("count", doubleValue=3.0),
            ],
        })

    def test_timestamp_is_utc_datetime(self):
        ts = self.event.timestamp
        self.assertIsInstance(ts, datetime)
        self.assertEqual(ts.tzinfo, timezone.utc)

    def test_get_attr_found(self):
        self.assertEqual(self.event.get_attr("severity"), "WARN")

    def test_get_attr_not_found(self):
        self.assertIsNone(self.event.get_attr("missing"))

    def test_get_attr_as_float_found(self):
        self.assertAlmostEqual(self.event.get_attr_as_float("count"), 3.0)

    def test_get_attr_as_float_not_found(self):
        self.assertIsNone(self.event.get_attr_as_float("missing"))


# ---------------------------------------------------------------------------
# OTLPEventsRecord
# ---------------------------------------------------------------------------

def _otlp_events_wrapper(service_name: str = "svc") -> dict:
    return {
        "resourceLogs": [
            {
                "resource": _resource_dict(
                    _attr_dict("service.name", stringValue=service_name)
                ),
                "scopeLogs": [
                    {
                        "scope": {"name": "log.scope"},
                        "logRecords": [_event_dict_plain_body("log line")],
                    }
                ],
            }
        ]
    }


def _simplified_events_dict(service_name: str = "svc") -> dict:
    return {
        "resource": _resource_dict(
            _attr_dict("service.name", stringValue=service_name)
        ),
        "scopeLogs": [
            {
                "scope": {"name": "simple.log.scope"},
                "logRecords": [_event_dict_plain_body("simple log")],
            }
        ],
    }


class TestOTLPEventsRecordFromDict(unittest.TestCase):

    def test_otlp_wrapper_format(self):
        rec = OTLPEventsRecord.from_dict(_otlp_events_wrapper())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(rec.scope_name, "log.scope")
        self.assertEqual(len(rec.log_records), 1)
        self.assertEqual(rec.log_records[0].body, "log line")

    def test_otlp_wrapper_empty_resource_logs_list(self):
        """Empty resourceLogs: OTLP shape detected, empty record — no IndexError."""
        rec = OTLPEventsRecord.from_dict({"resourceLogs": []})
        self.assertEqual(rec.log_records, [])
        self.assertEqual(rec.scope_name, "")

    def test_simplified_format(self):
        rec = OTLPEventsRecord.from_dict(_simplified_events_dict())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(rec.scope_name, "simple.log.scope")
        self.assertEqual(len(rec.log_records), 1)
        self.assertEqual(rec.log_records[0].body, "simple log")

    def test_empty_dict_gives_empty_record(self):
        rec = OTLPEventsRecord.from_dict({})
        self.assertEqual(rec.log_records, [])
        self.assertEqual(rec.scope_name, "")


# ---------------------------------------------------------------------------
# OTLPSpan
# ---------------------------------------------------------------------------

_SPAN_START_NS = 1_700_000_000_000_000_000
_SPAN_END_NS = _SPAN_START_NS + 500_000_000  # 500 ms later


def _span_dict(
    name: str = "my.span",
    start_ns: int = _SPAN_START_NS,
    end_ns: int = _SPAN_END_NS,
    attrs=None,
) -> dict:
    d: dict = {
        "traceId": "abc123",
        "spanId": "def456",
        "name": name,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
    }
    if attrs:
        d["attributes"] = attrs
    return d


class TestOTLPSpanFromDict(unittest.TestCase):

    def test_basic_parse(self):
        s = OTLPSpan.from_dict(_span_dict())
        self.assertEqual(s.trace_id, "abc123")
        self.assertEqual(s.span_id, "def456")
        self.assertEqual(s.name, "my.span")
        self.assertEqual(s.start_time_unix_nano, _SPAN_START_NS)
        self.assertEqual(s.end_time_unix_nano, _SPAN_END_NS)

    def test_attributes_parsed(self):
        s = OTLPSpan.from_dict(
            _span_dict(attrs=[_attr_dict("http.method", stringValue="GET")])
        )
        self.assertEqual(len(s.attributes), 1)
        self.assertEqual(s.attributes[0].key, "http.method")

    def test_defaults_when_fields_missing(self):
        s = OTLPSpan.from_dict({})
        self.assertEqual(s.trace_id, "")
        self.assertEqual(s.span_id, "")
        self.assertEqual(s.name, "")
        self.assertEqual(s.start_time_unix_nano, 0)
        self.assertEqual(s.end_time_unix_nano, 0)


class TestOTLPSpanProperties(unittest.TestCase):

    def setUp(self):
        self.span = OTLPSpan.from_dict(
            _span_dict(
                start_ns=_SPAN_START_NS,
                end_ns=_SPAN_END_NS,
                attrs=[_attr_dict("db.system", stringValue="postgres")],
            )
        )

    def test_duration_ms(self):
        # _SPAN_END_NS - _SPAN_START_NS = 500_000_000 ns = 500 ms
        self.assertAlmostEqual(self.span.duration_ms, 500.0, places=3)

    def test_start_timestamp_is_utc_datetime(self):
        ts = self.span.start_timestamp
        self.assertIsInstance(ts, datetime)
        self.assertEqual(ts.tzinfo, timezone.utc)

    def test_get_attr_found(self):
        self.assertEqual(self.span.get_attr("db.system"), "postgres")

    def test_get_attr_not_found(self):
        self.assertIsNone(self.span.get_attr("missing"))


# ---------------------------------------------------------------------------
# OTLPSpansRecord
# ---------------------------------------------------------------------------

def _otlp_spans_wrapper(service_name: str = "svc") -> dict:
    return {
        "resourceSpans": [
            {
                "resource": _resource_dict(
                    _attr_dict("service.name", stringValue=service_name)
                ),
                "scopeSpans": [
                    {
                        "spans": [_span_dict()],
                    }
                ],
            }
        ]
    }


def _simplified_spans_dict(service_name: str = "svc") -> dict:
    return {
        "resource": _resource_dict(
            _attr_dict("service.name", stringValue=service_name)
        ),
        "scopeSpans": [
            {
                "spans": [_span_dict(name="simple.span")],
            }
        ],
    }


class TestOTLPSpansRecordFromDict(unittest.TestCase):

    def test_otlp_wrapper_format(self):
        rec = OTLPSpansRecord.from_dict(_otlp_spans_wrapper())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(len(rec.spans), 1)
        self.assertEqual(rec.spans[0].name, "my.span")

    def test_otlp_wrapper_empty_resource_spans_list(self):
        """Empty resourceSpans: OTLP shape detected, empty record — no IndexError."""
        rec = OTLPSpansRecord.from_dict({"resourceSpans": []})
        self.assertEqual(rec.spans, [])

    def test_simplified_format(self):
        rec = OTLPSpansRecord.from_dict(_simplified_spans_dict())
        self.assertEqual(rec.resource.service_name, "svc")
        self.assertEqual(len(rec.spans), 1)
        self.assertEqual(rec.spans[0].name, "simple.span")

    def test_empty_dict_gives_empty_record(self):
        rec = OTLPSpansRecord.from_dict({})
        self.assertEqual(rec.spans, [])

    def test_resource_attributes_accessible_on_spans(self):
        rec = OTLPSpansRecord.from_dict(_otlp_spans_wrapper(service_name="trace-svc"))
        self.assertEqual(rec.resource.service_name, "trace-svc")


if __name__ == "__main__":
    unittest.main()
