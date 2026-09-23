"""Tests for worker.qwen_telemetry — OTLP span/metrics shape, endpoint
resolution, and non-fatal export.

The whole value of the shape tests is the round trip: build_job_span/
build_job_metrics output must parse back through the REAL reader dataclasses
(telemetry.otel.models.OTLPSpansRecord.from_dict, OTLPMetricsRecord.from_dict
and friends), not merely match a hand-written expected dict. A hand-written
dict would pass even if the shape were wrong for the reader that actually
consumes it in production.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from telemetry.otel.models import OTLPMetricsRecord, OTLPSpansRecord


class QwenTelemetryShapeTests(unittest.TestCase):
    """build_job_span's output round-trips through OTLPSpansRecord.from_dict."""

    def _build(self, **attr_overrides: object) -> dict[str, object]:
        from worker.qwen_telemetry import build_job_span

        attrs: dict[str, object] = {
            "qwen.job_id": "job-123",
            "qwen.job_type": "qwen_patch",
            "qwen.model": "qwen2.5-coder:14b",
            "qwen.outcome": "success",
            "qwen.attempt": 1,
            "qwen.patch_valid": True,
        }
        attrs.update(attr_overrides)
        start_ns = 1_700_000_000_000_000_000
        end_ns = start_ns + 5_000_000_000  # +5s
        return build_job_span(attrs, start_ns, end_ns)

    def test_round_trips_through_otlp_spans_record(self) -> None:
        payload = self._build()

        record = OTLPSpansRecord.from_dict(payload)

        self.assertIsInstance(record, OTLPSpansRecord)
        self.assertEqual(len(record.spans), 1)
        span = record.spans[0]
        self.assertEqual(span.name, "qwen.job")

    def test_expected_attributes_present_on_parsed_span(self) -> None:
        payload = self._build()
        record = OTLPSpansRecord.from_dict(payload)
        span = record.spans[0]

        self.assertEqual(span.get_attr("qwen.job_id"), "job-123")
        self.assertEqual(span.get_attr("qwen.job_type"), "qwen_patch")
        self.assertEqual(span.get_attr("qwen.model"), "qwen2.5-coder:14b")
        self.assertEqual(span.get_attr("qwen.outcome"), "success")

    def test_duration_derived_from_start_end_ns(self) -> None:
        payload = self._build()
        record = OTLPSpansRecord.from_dict(payload)
        span = record.spans[0]

        self.assertEqual(span.duration_ms, 5000.0)

    def test_no_cost_attribute_is_present(self) -> None:
        """contract.json's telemetry.emits_cost is false — enforce it."""
        from worker.qwen_telemetry import build_job_span

        attrs: dict[str, object] = {
            "qwen.job_id": "job-cost-check",
            "qwen.job_type": "qwen_patch",
            "qwen.model": "qwen2.5-coder:14b",
            "qwen.outcome": "success",
            "qwen.attempt": 1,
            "qwen.patch_valid": True,
        }
        payload = build_job_span(attrs, 0, 1_000_000_000)

        record = OTLPSpansRecord.from_dict(payload)
        span = record.spans[0]
        keys = {attr.key for attr in span.attributes}
        self.assertNotIn("qwen.cost", keys)
        self.assertNotIn("cost", keys)
        for key in keys:
            self.assertNotIn("cost", key.lower())


class QwenTelemetryExportNonFatalTests(unittest.TestCase):
    """export_job_span is best-effort and swallows every error."""

    def test_export_swallows_post_failure_without_raising(self) -> None:
        from worker.qwen_telemetry import export_job_span

        attrs: dict[str, object] = {
            "qwen.job_id": "job-999",
            "qwen.job_type": "qwen_patch",
            "qwen.model": "qwen2.5-coder:14b",
            "qwen.outcome": "success",
            "qwen.attempt": 1,
            "qwen.patch_valid": True,
        }

        with mock.patch(
            "worker.qwen_telemetry._post",
            side_effect=RuntimeError("collector unreachable"),
        ) as mock_post:
            try:
                export_job_span(attrs, 0, 1_000_000_000)
            except Exception as exc:  # pragma: no cover - defensive; test must fail loudly if this fires
                self.fail(f"export_job_span raised despite being best-effort: {exc!r}")

        mock_post.assert_called_once()

    def test_export_calls_post_on_success_path(self) -> None:
        from worker.qwen_telemetry import export_job_span

        attrs: dict[str, object] = {
            "qwen.job_id": "job-ok",
            "qwen.job_type": "qwen_patch",
            "qwen.model": "qwen2.5-coder:14b",
            "qwen.outcome": "success",
            "qwen.attempt": 1,
            "qwen.patch_valid": True,
        }

        with mock.patch("worker.qwen_telemetry._post") as mock_post:
            export_job_span(attrs, 0, 1_000_000_000)

        mock_post.assert_called_once()


_METRIC_ATTRS: dict[str, object] = {
    "qwen.job_id": "job-metrics",
    "qwen.job_type": "qwen_patch",
    "qwen.model": "qwen2.5-coder:14b",
    "qwen.outcome": "success",
}


class _OtelEnvIsolationMixin:
    """Clears every OTel exporter env var this module reads before each test."""

    _OTEL_VARS = (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
    )

    def setUp(self) -> None:  # NOSONAR - required unittest lifecycle method name
        super().setUp()  # type: ignore[misc]
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]
        for var in self._OTEL_VARS:
            os.environ.pop(var, None)


class QwenTelemetryMetricsShapeTests(_OtelEnvIsolationMixin, unittest.TestCase):
    """build_job_metrics' output round-trips through the REAL
    telemetry.otel.models metrics parser (OTLPMetricsRecord.from_dict)."""

    def test_round_trips_through_otlp_metrics_record(self) -> None:
        from worker.qwen_telemetry import build_job_metrics

        payload = build_job_metrics(_METRIC_ATTRS, duration_ms=1234.5, prompt_tokens=84, completion_tokens=57)

        record = OTLPMetricsRecord.from_dict(payload)

        self.assertIsInstance(record, OTLPMetricsRecord)
        names = {m.name for m in record.metrics}
        self.assertEqual(
            names,
            {"qwen.prompt_tokens", "qwen.completion_tokens", "qwen.generation_duration_ms"},
        )

    def test_metric_values_and_attributes_round_trip(self) -> None:
        from worker.qwen_telemetry import build_job_metrics

        payload = build_job_metrics(_METRIC_ATTRS, duration_ms=1234.5, prompt_tokens=84, completion_tokens=57)
        record = OTLPMetricsRecord.from_dict(payload)

        by_name = {m.name: m for m in record.metrics}
        prompt_dp = by_name["qwen.prompt_tokens"].data_points[0]
        completion_dp = by_name["qwen.completion_tokens"].data_points[0]
        duration_dp = by_name["qwen.generation_duration_ms"].data_points[0]

        self.assertEqual(prompt_dp.value, 84.0)
        self.assertEqual(completion_dp.value, 57.0)
        self.assertEqual(duration_dp.value, 1234.5)
        self.assertEqual(prompt_dp.get_attr("qwen.job_id"), "job-metrics")
        self.assertEqual(prompt_dp.get_attr("qwen.outcome"), "success")
        self.assertEqual(record.resource.get_attr("service.name"), "qwen-worker")

    def test_token_metrics_absent_when_ollama_gave_no_counts(self) -> None:
        from worker.qwen_telemetry import build_job_metrics

        payload = build_job_metrics(_METRIC_ATTRS, duration_ms=500.0, prompt_tokens=None, completion_tokens=None)
        record = OTLPMetricsRecord.from_dict(payload)

        names = {m.name for m in record.metrics}
        self.assertEqual(names, {"qwen.generation_duration_ms"})
        self.assertNotIn("qwen.prompt_tokens", names)
        self.assertNotIn("qwen.completion_tokens", names)

    def test_token_metrics_present_with_exact_values_when_ollama_gave_counts(self) -> None:
        from worker.qwen_telemetry import build_job_metrics

        payload = build_job_metrics(_METRIC_ATTRS, duration_ms=500.0, prompt_tokens=12, completion_tokens=34)
        record = OTLPMetricsRecord.from_dict(payload)

        by_name = {m.name: m for m in record.metrics}
        self.assertEqual(by_name["qwen.prompt_tokens"].data_points[0].value, 12.0)
        self.assertEqual(by_name["qwen.completion_tokens"].data_points[0].value, 34.0)

    def test_no_cost_anywhere_in_serialized_payload(self) -> None:
        """contract.json's telemetry.emits_cost is false — enforce it on metrics too."""
        from worker.qwen_telemetry import build_job_metrics

        payload = build_job_metrics(_METRIC_ATTRS, duration_ms=500.0, prompt_tokens=12, completion_tokens=34)
        serialized = json.dumps(payload).lower()

        self.assertNotIn("cost", serialized)


class QwenTelemetryEndpointResolutionTests(_OtelEnvIsolationMixin, unittest.TestCase):
    """Per-signal env var wins; else the generic var + path, but only under an
    HTTP protocol; else the http://localhost:4318 default. See
    src/telemetry/otel/health.py:53-56, which documents pointing the generic
    endpoint var at the collector's gRPC port with protocol=grpc — appending
    an HTTP path to that endpoint must NOT happen."""

    def test_per_signal_var_wins_used_as_is_no_path_appended(self) -> None:
        from worker.qwen_telemetry import _resolve_traces_endpoint

        os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "https://collector.example/custom"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"

        self.assertEqual(_resolve_traces_endpoint(), "https://collector.example/custom")

    def test_per_signal_metrics_var_wins(self) -> None:
        from worker.qwen_telemetry import _resolve_metrics_endpoint

        os.environ["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] = "https://collector.example/m"

        self.assertEqual(_resolve_metrics_endpoint(), "https://collector.example/m")

    def test_generic_var_with_grpc_protocol_falls_back_to_default(self) -> None:
        """The health.py-documented scenario: OTEL_EXPORTER_OTLP_ENDPOINT set to
        the gRPC port with protocol=grpc must NOT have /v1/traces appended to
        it — that would silently drop every export against a gRPC listener."""
        from worker.qwen_telemetry import _resolve_traces_endpoint

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"

        self.assertEqual(_resolve_traces_endpoint(), "http://localhost:4318/v1/traces")

    def test_generic_var_with_http_protobuf_uses_generic_plus_path(self) -> None:
        from worker.qwen_telemetry import _resolve_metrics_endpoint

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4318"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"

        self.assertEqual(_resolve_metrics_endpoint(), "http://collector:4318/v1/metrics")

    def test_generic_var_with_http_json_uses_generic_plus_path(self) -> None:
        from worker.qwen_telemetry import _resolve_traces_endpoint

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4318"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"

        self.assertEqual(_resolve_traces_endpoint(), "http://collector:4318/v1/traces")

    def test_trailing_slash_stripped_before_appending_path(self) -> None:
        from worker.qwen_telemetry import _resolve_metrics_endpoint

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4318/"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"

        self.assertEqual(_resolve_metrics_endpoint(), "http://collector:4318/v1/metrics")

    def test_nothing_set_falls_back_to_default(self) -> None:
        from worker.qwen_telemetry import _resolve_metrics_endpoint, _resolve_traces_endpoint

        self.assertEqual(_resolve_traces_endpoint(), "http://localhost:4318/v1/traces")
        self.assertEqual(_resolve_metrics_endpoint(), "http://localhost:4318/v1/metrics")

    def test_per_signal_protocol_overrides_generic_protocol(self) -> None:
        """A per-signal protocol var (e.g. metrics=http/json while the generic
        var says grpc) is consulted before falling back to the generic one."""
        from worker.qwen_telemetry import _resolve_metrics_endpoint

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4318"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"] = "http/json"

        self.assertEqual(_resolve_metrics_endpoint(), "http://collector:4318/v1/metrics")


class QwenTelemetryMetricsExportNonFatalTests(_OtelEnvIsolationMixin, unittest.TestCase):
    """export_job_metrics is best-effort and swallows every error."""

    def test_export_swallows_post_failure_without_raising(self) -> None:
        from worker.qwen_telemetry import export_job_metrics

        with mock.patch(
            "worker.qwen_telemetry._post",
            side_effect=RuntimeError("collector unreachable"),
        ) as mock_post:
            try:
                export_job_metrics(_METRIC_ATTRS, 500.0, 12, 34)
            except Exception as exc:  # pragma: no cover - defensive; test must fail loudly if this fires
                self.fail(f"export_job_metrics raised despite being best-effort: {exc!r}")

        mock_post.assert_called_once()

    def test_export_calls_post_on_success_path(self) -> None:
        from worker.qwen_telemetry import export_job_metrics

        with mock.patch("worker.qwen_telemetry._post") as mock_post:
            export_job_metrics(_METRIC_ATTRS, 500.0, 12, 34)

        mock_post.assert_called_once()


class QwenTelemetryExportIndependenceTests(_OtelEnvIsolationMixin, unittest.TestCase):
    """Span and metrics export are independent: one raising must not skip
    the other, at the qwen_telemetry level."""

    def test_span_export_failure_does_not_skip_metrics_export(self) -> None:
        from worker.qwen_telemetry import export_job_metrics, export_job_span

        with mock.patch(
            "worker.qwen_telemetry._post", side_effect=RuntimeError("down")
        ) as mock_post:
            export_job_span(_METRIC_ATTRS, 0, 1_000_000_000)
            export_job_metrics(_METRIC_ATTRS, 500.0, 12, 34)

        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
