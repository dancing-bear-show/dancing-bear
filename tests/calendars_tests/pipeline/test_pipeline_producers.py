"""Tests for calendar pipeline processors and producers (Gmail and Outlook)."""

import tempfile
from contextlib import redirect_stdout
import io
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from calendars.pipeline import (
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
    OutlookDedupProcessor,
    OutlookDedupProducer,
    OutlookDedupRequest,
    OutlookDedupRequestConsumer,
)


from tests.calendars_tests.fixtures import make_occurrence as _make_occurrence  # noqa: E402


class CalendarPipelineTests(TestCase):

    def test_outlook_verify_processor_counts_duplicates_and_missing_together(self):
        """Two config entries — one with a matching real event (duplicate),
        one with none (missing) — exercises the missing-count branch, which
        neither test_outlook_verify_processor test above ever triggers
        (both use a single config entry that always matches)."""
        cfg = {
            "events": [
                {
                    "subject": "Match",
                    "repeat": "weekly",
                    "byday": ["MO"],
                    "start_time": "17:00",
                    "end_time": "17:30",
                    "range": {"start_date": "2025-01-01", "until": "2025-02-01"},
                },
                {
                    "subject": "Missing",
                    "repeat": "weekly",
                    "byday": ["WE"],
                    "start_time": "17:00",
                    "end_time": "17:30",
                    "range": {"start_date": "2025-01-01", "until": "2025-02-01"},
                },
            ]
        }
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml") as tf:
            import yaml
            yaml.safe_dump(cfg, tf)
            tf_path = Path(tf.name)
        svc = MagicMock()
        # Only a Monday 17:00 event exists — matches "Match", nothing matches "Missing".
        svc.list_events_in_range.return_value = [
            {
                "subject": "Match",
                "start": {"dateTime": "2025-01-06T17:00:00"},
                "end": {"dateTime": "2025-01-06T17:30:00"},
                "type": "singleInstance",
            },
        ]
        request = OutlookVerifyRequest(config_path=tf_path, calendar=None, service=svc)
        env = OutlookVerifyProcessor().process(
            OutlookVerifyRequestConsumer(request).consume()
        )
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.total, 2)  # type: ignore[union-attr]
        self.assertEqual(env.payload.duplicates, 1)  # type: ignore[union-attr]
        self.assertEqual(env.payload.missing, 1)  # type: ignore[union-attr]
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        out = buf.getvalue()
        self.assertIn("Checked 2 recurring entries", out)
        self.assertIn("Duplicates: 1, Missing: 1", out)

    def test_outlook_dedup_processor_prefers_deleting_nonstandard_location(self):
        """prefer_delete_nonstandard + keep_newest: deletes the master without a
        standardized (address-bearing or parenthesized) location, keeping the
        newer standardized one — untested combination anywhere else."""
        svc = MagicMock()
        svc.list_calendar_view.return_value = [
            _make_occurrence(
                "Soccer", "A", "2025-01-06T17:00:00+00:00", "2025-01-06T17:30:00+00:00", "2024-01-01T00:00:00Z",
            ),
            _make_occurrence(
                "Soccer", "B", "2025-01-13T17:00:00+00:00", "2025-01-13T17:30:00+00:00", "2024-06-01T00:00:00Z",
                location={"address": {"street": "X", "city": "Y"}},
            ),
        ]
        svc.delete_event_by_id.return_value = True
        request = OutlookDedupRequest(
            service=svc,
            apply=True,
            prefer_delete_nonstandard=True,
            keep_newest=True,
            from_date="2025-01-01",
            to_date="2025-02-01",
        )
        env = OutlookDedupProcessor().process(OutlookDedupRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.deleted, 1)  # type: ignore[union-attr]
        svc.delete_event_by_id.assert_called_once_with("A")
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        text = buf.getvalue()
        self.assertIn("Deleted", text)
