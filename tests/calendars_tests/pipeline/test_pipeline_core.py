"""Tests for core pipeline infrastructure: RequestConsumer, BaseProducer, run_pipeline, check_service_required."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from tests.fixtures import test_path
from tests.calendars_tests.fixtures import NoOpProducer, make_mock_processor

from core.pipeline import ResultEnvelope
from calendars.pipeline import (
    GmailAuth,
    GmailMailListRequest,
    GmailSweepTopRequest,
    GmailSweepTopRequestConsumer,
    OutlookVerifyRequest,
    OutlookVerifyResult,
    OutlookVerifyProducer,
    OutlookVerifyRequestConsumer,
    BaseProducer,
    RequestConsumer,
)


class RequestConsumerTests(TestCase):
    """Tests for the generic RequestConsumer class."""

    def test_request_consumer_returns_request(self):
        """RequestConsumer.consume() returns the original request object."""
        request = GmailMailListRequest(
            auth=GmailAuth(None, None, None, None),
            query="test",
            from_text=None,
            days=7,
            pages=1,
            page_size=10,
            inbox_only=True,
        )
        consumer = RequestConsumer(request)
        result = consumer.consume()
        self.assertIs(result, request)

    def test_request_consumer_works_with_type_alias(self):
        """Type alias consumers work correctly with RequestConsumer."""
        request = OutlookVerifyRequest(
            config_path=Path(test_path("test.yaml")),  # noqa: S108 - test fixture path
            calendar="Family",
            service=MagicMock(),
        )
        # Using the type alias
        consumer = OutlookVerifyRequestConsumer(request)
        result = consumer.consume()
        self.assertIs(result, request)
        self.assertEqual(result.calendar, "Family")

    def test_request_consumer_preserves_all_fields(self):
        """RequestConsumer preserves all request fields."""
        auth = GmailAuth("profile", "creds", "token", "cache")
        request = GmailSweepTopRequest(
            auth=auth,
            query="from:test",
            from_text="alerts",
            days=30,
            pages=5,
            page_size=50,
            inbox_only=False,
            top=10,
            out_path=Path(test_path("out.yaml")),  # noqa: S108 - test fixture path
        )
        consumer = GmailSweepTopRequestConsumer(request)
        result = consumer.consume()
        self.assertEqual(result.auth.profile, "profile")
        self.assertEqual(result.query, "from:test")
        self.assertEqual(result.days, 30)
        self.assertEqual(result.top, 10)


class BaseProducerTests(TestCase):
    """Tests for the BaseProducer template method pattern."""

    def test_base_producer_handles_error_result(self):
        """BaseProducer.produce() prints error message for failed results."""
        env = ResultEnvelope(status="error", diagnostics={"message": "Something went wrong", "code": 1})
        buf = io.StringIO()
        with redirect_stderr(buf):
            OutlookVerifyProducer().produce(env)
        self.assertIn("Something went wrong", buf.getvalue())

    def test_base_producer_handles_error_without_message(self):
        """BaseProducer.produce() handles errors without message gracefully."""
        env = ResultEnvelope(status="error", diagnostics={"code": 1})
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        # Should not raise, just return without printing
        self.assertEqual("", buf.getvalue())

    def test_base_producer_calls_produce_success(self):
        """BaseProducer.produce() delegates to _produce_success for successful results."""
        payload = OutlookVerifyResult(logs=["test log"], total=5, duplicates=2, missing=1)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("test log", output)
        self.assertIn("Checked 5 recurring entries", output)
        self.assertIn("Duplicates: 2", output)
        self.assertIn("Missing: 1", output)

    def test_base_producer_print_logs_helper(self):
        """BaseProducer.print_logs() prints each log line."""
        producer = OutlookVerifyProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.print_logs(["line1", "line2", "line3"])
        output = buf.getvalue()
        self.assertIn("line1", output)
        self.assertIn("line2", output)
        self.assertIn("line3", output)

    def test_base_producer_print_error_returns_true_on_error(self):
        """BaseProducer.print_error() returns True when result has error."""
        env = ResultEnvelope(status="error", diagnostics={"message": "fail"})
        buf = io.StringIO()
        with redirect_stderr(buf):
            result = BaseProducer().print_error(env)
        self.assertTrue(result)
        self.assertIn("fail", buf.getvalue())

    def test_base_producer_print_error_returns_false_on_success(self):
        """BaseProducer.print_error() returns False when result is successful."""
        env = ResultEnvelope(status="success", payload=None)
        result = BaseProducer().print_error(env)
        self.assertFalse(result)


class RunPipelineTests(TestCase):
    """Tests for the run_pipeline helper function."""

    def test_run_pipeline_returns_zero_on_success(self):
        """run_pipeline() returns 0 when processor returns success."""
        from core.pipeline import run_pipeline

        processor = make_mock_processor(ResultEnvelope(status="success", payload={"data": "test"}))
        result = run_pipeline({"test": 123}, processor, NoOpProducer)
        self.assertEqual(0, result)

    def test_run_pipeline_returns_error_code_on_failure(self):
        """run_pipeline() returns error code from diagnostics on failure."""
        from core.pipeline import run_pipeline

        processor = make_mock_processor(ResultEnvelope(status="error", diagnostics={"code": 42, "message": "fail"}))
        result = run_pipeline({}, processor, NoOpProducer)
        self.assertEqual(42, result)

    def test_run_pipeline_returns_default_code_on_failure_without_code(self):
        """run_pipeline() returns 2 when error has no code in diagnostics."""
        from core.pipeline import run_pipeline

        processor = make_mock_processor(ResultEnvelope(status="error", diagnostics={"message": "fail"}))
        result = run_pipeline({}, processor, NoOpProducer)
        self.assertEqual(2, result)

    def test_run_pipeline_calls_producer_with_envelope(self):
        """run_pipeline() passes the envelope from processor to producer."""
        from core.pipeline import run_pipeline

        captured_envelope = []

        class MockProcessor:
            def process(self, req):
                return ResultEnvelope(status="success", payload={"from_request": req})

        class CapturingProducer:
            def produce(self, env):
                captured_envelope.append(env)

        run_pipeline({"key": "value"}, MockProcessor, CapturingProducer)
        self.assertEqual(1, len(captured_envelope))
        self.assertEqual({"from_request": {"key": "value"}}, captured_envelope[0].payload)

    def test_run_pipeline_passes_request_to_processor(self):
        """run_pipeline() passes the request directly to processor.process()."""
        from core.pipeline import run_pipeline

        captured_request = []

        class CapturingProcessor:
            def process(self, req):
                captured_request.append(req)
                return ResultEnvelope(status="success", payload=None)

        test_request = {"field1": "a", "field2": 42}
        run_pipeline(test_request, CapturingProcessor, NoOpProducer)
        self.assertEqual(1, len(captured_request))
        self.assertEqual(test_request, captured_request[0])


class CheckServiceRequiredTests(TestCase):
    """Tests for the check_service_required helper function."""

    def test_check_service_required_returns_none_when_service_exists(self):
        """check_service_required() returns None when service is not None."""
        from calendars.pipeline_base import check_service_required

        # Should not raise for valid service
        check_service_required(MagicMock())

    def test_check_service_required_raises_when_none(self):
        """check_service_required() raises ValueError when service is None."""
        from calendars.pipeline_base import check_service_required

        with self.assertRaises(ValueError) as ctx:
            check_service_required(None)
        self.assertIn("service is required", str(ctx.exception))

    def test_check_service_required_uses_custom_error_message(self):
        """check_service_required() uses custom error message when provided."""
        from calendars.pipeline_base import check_service_required

        with self.assertRaises(ValueError) as ctx:
            check_service_required(None, error_msg="Custom error message")
        self.assertEqual("Custom error message", str(ctx.exception))

    def test_check_service_required_in_processor_pattern(self):
        """check_service_required() works within SafeProcessor pattern."""
        from calendars.pipeline_base import check_service_required

        # Valid service - no exception
        service = MagicMock()
        try:
            check_service_required(service)
        except ValueError:
            self.fail("Should not raise for valid service")

        # None service - raises, which SafeProcessor catches
        with self.assertRaises(ValueError):
            check_service_required(None)


if __name__ == "__main__":
    unittest.main()
