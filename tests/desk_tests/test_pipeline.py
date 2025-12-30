"""Tests for desk/pipeline.py processor components."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from io import StringIO

from desk.pipeline import (
    ScanRequest,
    ScanProcessor,
    PlanRequest,
    PlanProcessor,
    ApplyRequest,
    ApplyProcessor,
    ReportProducer,
    ApplyResultProducer,
)
from core.pipeline import ResultEnvelope


class ScanRequestTests(unittest.TestCase):
    def test_create_request(self):
        req = ScanRequest(
            paths=["/path1", "/path2"],
            min_size="50MB",
            older_than="30d",
            include_duplicates=True,
            top_dirs=10,
        )
        self.assertEqual(req.paths, ["/path1", "/path2"])
        self.assertEqual(req.min_size, "50MB")
        self.assertEqual(req.older_than, "30d")
        self.assertTrue(req.include_duplicates)


class ScanProcessorTests(unittest.TestCase):
    def test_process_calls_runner(self):
        mock_runner = MagicMock(return_value={"large_files": []})
        processor = ScanProcessor(runner=mock_runner)

        req = ScanRequest(
            paths=["/test"],
            min_size="50MB",
            older_than=None,
            include_duplicates=False,
            top_dirs=5,
        )
        result = processor.process(req)

        mock_runner.assert_called_once_with(
            paths=["/test"],
            min_size="50MB",
            older_than=None,
            include_duplicates=False,
            top_dirs=5,
        )
        self.assertEqual(result, {"large_files": []})

    def test_process_with_default_runner(self):
        processor = ScanProcessor()
        req = ScanRequest(
            paths=["/nonexistent"],
            min_size="1GB",
            older_than=None,
            include_duplicates=False,
            top_dirs=5,
        )
        result = processor.process(req)

        self.assertIn("large_files", result)


class PlanRequestTests(unittest.TestCase):
    def test_create_request(self):
        req = PlanRequest(config_path="/path/to/config.yaml")
        self.assertEqual(req.config_path, "/path/to/config.yaml")


class PlanProcessorTests(unittest.TestCase):
    def test_process_calls_planner(self):
        mock_planner = MagicMock(return_value={"operations": []})
        processor = PlanProcessor(planner=mock_planner)

        req = PlanRequest(config_path="/test/config.yaml")
        result = processor.process(req)

        mock_planner.assert_called_once_with("/test/config.yaml")
        self.assertEqual(result, {"operations": []})


class ApplyRequestTests(unittest.TestCase):
    def test_create_request(self):
        req = ApplyRequest(plan_path="/path/to/plan.json", dry_run=True)
        self.assertEqual(req.plan_path, "/path/to/plan.json")
        self.assertTrue(req.dry_run)


class ApplyProcessorTests(unittest.TestCase):
    def test_process_success(self):
        mock_applier = MagicMock()
        processor = ApplyProcessor(applier=mock_applier)

        req = ApplyRequest(plan_path="/test/plan.json", dry_run=False)
        result = processor.process(req)

        mock_applier.assert_called_once_with("/test/plan.json", dry_run=False)
        self.assertIsInstance(result, ResultEnvelope)
        self.assertTrue(result.ok())

    def test_process_error(self):
        mock_applier = MagicMock(side_effect=Exception("apply failed"))
        processor = ApplyProcessor(applier=mock_applier)

        req = ApplyRequest(plan_path="/test/plan.json", dry_run=False)
        result = processor.process(req)

        self.assertIsInstance(result, ResultEnvelope)
        self.assertFalse(result.ok())
        self.assertEqual(result.diagnostics["error"], "apply failed")

    def test_process_dry_run(self):
        mock_applier = MagicMock()
        processor = ApplyProcessor(applier=mock_applier)

        req = ApplyRequest(plan_path="/test/plan.json", dry_run=True)
        processor.process(req)

        mock_applier.assert_called_once_with("/test/plan.json", dry_run=True)


class ReportProducerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_produce_to_stdout(self):
        producer = ReportProducer(out_path=None)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            producer.produce({"key": "value"})
            output = mock_out.getvalue()

        self.assertIn("key", output)
        self.assertIn("value", output)

    def test_produce_to_file(self):
        out_path = os.path.join(self.tmpdir, "report.json")
        producer = ReportProducer(out_path=out_path)

        producer.produce({"key": "value"})

        self.assertTrue(os.path.exists(out_path))


class ApplyResultProducerTests(unittest.TestCase):
    def test_produce_success(self):
        producer = ApplyResultProducer()
        result = ResultEnvelope(status="success")

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            producer.produce(result)
            output = mock_out.getvalue()

        # Success should not print error
        self.assertNotIn("failed", output.lower())

    def test_produce_error(self):
        producer = ApplyResultProducer()
        result = ResultEnvelope(status="error", diagnostics={"error": "test error"})

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            producer.produce(result)
            output = mock_out.getvalue()

        self.assertIn("failed", output.lower())
        self.assertIn("test error", output)


if __name__ == "__main__":
    unittest.main()
