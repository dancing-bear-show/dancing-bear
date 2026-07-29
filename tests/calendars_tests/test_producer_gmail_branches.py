"""Tests for uncovered Gmail producer output branches and helpers."""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope


class TestGmailSweepTopProducerOutPath(unittest.TestCase):
    """Tests for GmailSweepTopProducer._produce_success with out_path set."""

    def test_produce_no_senders_prints_no_stats(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        payload = GmailSweepTopResult(top_senders=[], freq_days=30, inbox_only=True, out_path=None)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(env)
        self.assertIn("No sender stats available", buf.getvalue())

    def test_produce_with_out_path_writes_filters_yaml(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "filters.yaml"
            payload = GmailSweepTopResult(
                top_senders=[("spam@example.com", 42), ("noise@foo.com", 10)],
                freq_days=14,
                inbox_only=False,
                out_path=out_path,
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailSweepTopProducer().produce(env)
            output = buf.getvalue()
            self.assertIn("spam@example.com", output)
            self.assertIn("noise@foo.com", output)
            self.assertIn(str(out_path), output)
            # File should have been written with filter content
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("spam@example.com", content)

    def test_produce_with_senders_no_out_path(self):
        from calendars.gmail_pipelines import GmailSweepTopProducer, GmailSweepTopResult
        payload = GmailSweepTopResult(
            top_senders=[("sender@example.com", 5)],
            freq_days=7,
            inbox_only=True,
            out_path=None,
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("sender@example.com", output)
        self.assertIn("7d", output)
        # No "Wrote" line since out_path is None
        self.assertNotIn("Wrote", output)


class TestGmailServiceBuildActiveRHQueryDefault(unittest.TestCase):
    """Tests for GmailService.build_activerh_query with programs default."""

    def test_build_activerh_query_uses_default_programs(self):
        from calendars.gmail_service import GmailService
        result = GmailService.build_activerh_query(days=30)
        # Without explicit programs, defaults include Swimmer, Chess, etc.
        # Result must be a non-empty string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_build_activerh_query_with_explicit_programs(self):
        from calendars.gmail_service import GmailService
        result = GmailService.build_activerh_query(days=7, programs=["Tennis"])
        self.assertIn("Tennis", result)

    def test_build_activerh_query_programs_none_uses_default(self):
        from calendars.gmail_service import GmailService
        # programs=None should trigger the default list
        result_none = GmailService.build_activerh_query(days=30, programs=None)
        result_default = GmailService.build_activerh_query(days=30)
        self.assertEqual(result_none, result_default)


class TestGmailServiceBuilderWithExplicitClass(unittest.TestCase):
    """Tests for GmailServiceBuilder.build with an explicit service_cls (line 63+)."""

    def test_build_passes_custom_service_cls(self):
        from calendars.pipeline_base import GmailServiceBuilder, GmailAuth
        custom_svc = MagicMock()
        auth = GmailAuth(profile=None, credentials=None, token=None, cache_dir=None)
        with patch("calendars.pipeline_base._build_gmail_service", return_value="fake_svc") as mock_build:
            result = GmailServiceBuilder.build(auth, service_cls=custom_svc)
        mock_build.assert_called_once_with(
            profile=None,
            cache_dir=None,
            credentials_path=None,
            token_path=None,
            service_cls=custom_svc,
        )
        self.assertEqual(result, "fake_svc")

    def test_build_uses_default_gmail_service_when_no_cls(self):
        from calendars.pipeline_base import GmailServiceBuilder, GmailAuth
        from calendars.gmail_service import GmailService
        auth = GmailAuth(profile=None, credentials=None, token=None, cache_dir=None)
        with patch("calendars.pipeline_base._build_gmail_service", return_value="svc") as mock_build:
            GmailServiceBuilder.build(auth)
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs["service_cls"], GmailService)


if __name__ == "__main__":
    unittest.main()
