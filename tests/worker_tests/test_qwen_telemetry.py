"""Tests for worker.qwen_telemetry — OTLP span shape and non-fatal export.

The whole value of these tests is the round trip: build_job_span's output
must parse back through the REAL reader dataclasses
(telemetry.otel.models.OTLPSpansRecord.from_dict and friends), not merely
match a hand-written expected dict. A hand-written dict would pass even if
the shape were wrong for the reader that actually consumes it in production.

worker.qwen_telemetry does not exist in this worktree yet (impl-handler owns
it, running in a parallel stage); ModuleNotFoundError here is expected.
"""

from __future__ import annotations

import unittest
from unittest import mock

from telemetry.otel.models import OTLPSpansRecord


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


if __name__ == "__main__":
    unittest.main()
