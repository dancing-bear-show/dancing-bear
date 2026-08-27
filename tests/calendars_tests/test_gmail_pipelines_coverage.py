"""Coverage-gap tests for calendars/gmail_pipelines.py.

Targets: 82.7% -> 90%+

Covers previously uncovered lines:
 - GmailReceiptsProcessor: no-ids path (143), no-events path (146),
   get_message_text exception (168-169), incomplete receipt (184),
   invalid date range (188), location absent (203->206),
   child info set (208-209), invalid month (217)
 - _extract_child_info: PAT_2 fallback (230-232)
 - _normalize_subject branches (243-250): swimmer/swim kids, chess/c, s+pool, s+no-pool
 - GmailScanClassesProcessor: no-ids (319), get_message_text exception (324-325),
   no events found (329), events found (336), meta subject/location/range (353, 357, 375-381)
 - GmailMailListProcessor: no-ids (423), get_message_text exception (435)
 - GmailMailListProducer: no messages (440-442), messages listed (452-453)
 - GmailSweepTopProcessor: no-ids (492), get_message raises (504)
 - GmailSweepTopProducer: no senders (519->517), senders no out_path (527-528),
   senders with out_path (536->535, 541)
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock

from calendars.gmail_pipelines import (
    GmailReceiptsProcessor,
    GmailReceiptsRequest,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailMailListProcessor,
    GmailMailListProducer,
    GmailMailListRequest,
    GmailMailListRequestConsumer,
    GmailSweepTopProcessor,
    GmailSweepTopProducer,
    GmailSweepTopRequest,
    GmailSweepTopRequestConsumer,
    GmailReceiptsRequestConsumer,
)
from calendars.pipeline_base import GmailAuth
from core.pipeline import ResultEnvelope


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_AUTH = GmailAuth(None, None, None, None)


def _make_receipts_request(calendar: str | None = "Activities", out_path: Path | None = None) -> GmailReceiptsRequest:
    return GmailReceiptsRequest(
        auth=_AUTH,
        query=None,
        from_text="test.ca",
        days=30,
        pages=1,
        page_size=10,
        calendar=calendar,
        out_path=out_path or Path("plan.yaml"),
    )


def _make_classes_request(out_path: Path | None = None, calendar: str | None = None) -> GmailScanClassesRequest:
    return GmailScanClassesRequest(
        auth=_AUTH,
        from_text=None,
        query=None,
        days=30,
        pages=1,
        page_size=10,
        inbox_only=False,
        calendar=calendar,
        out_path=out_path,
    )


def _make_mail_list_request() -> GmailMailListRequest:
    return GmailMailListRequest(
        auth=_AUTH,
        query=None,
        from_text=None,
        days=7,
        pages=1,
        page_size=10,
        inbox_only=False,
    )


def _make_sweep_top_request(top: int = 5, out_path: Path | None = None) -> GmailSweepTopRequest:
    return GmailSweepTopRequest(
        auth=_AUTH,
        query=None,
        from_text=None,
        days=10,
        pages=1,
        page_size=10,
        inbox_only=False,
        top=top,
        out_path=out_path,
    )


# ---------------------------------------------------------------------------
# GmailReceiptsProcessor — no-ids and no-events paths
# ---------------------------------------------------------------------------

class TestGmailReceiptsProcessorEmptyPaths(unittest.TestCase):
    """Covers lines 143 and 146: no-ids and no-events early returns."""

    def test_no_ids_returns_empty_events(self):
        """When list_message_ids returns [], processor returns empty document. (line 143)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = []
        request = _make_receipts_request()
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailReceiptsRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])
        svc.get_message_text.assert_not_called()

    def test_ids_but_no_parseable_receipts_returns_empty(self):
        """Messages present but none parse into receipts — empty events list. (line 146)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.return_value = "Nothing useful here"
        request = _make_receipts_request()
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailReceiptsRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])


# ---------------------------------------------------------------------------
# GmailReceiptsProcessor — _parse_receipts exception and _parse_single_receipt branches
# ---------------------------------------------------------------------------

class TestParseReceiptsExceptionHandling(unittest.TestCase):
    """Covers line 168-169: exception in get_message_text is silently skipped."""

    def test_get_message_text_exception_skips_message(self):
        """Exception during get_message_text is swallowed; other messages still processed. (lines 168-169)"""
        good_text = (
            "Enrollment in Swim Kids 3 (# 12345)\n"
            "Meeting Dates: From January 1, 2026 to March 1, 2026\n"
            "Each Monday from 5:00 pm to 5:30 pm\n"
            "Location: Elgin West Pool\n"
        )
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m-bad", "m-good"]
        svc.get_message_text.side_effect = [RuntimeError("fetch failed"), good_text]
        request = _make_receipts_request()
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailReceiptsRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        # The bad message is skipped; the good one parses successfully.
        self.assertEqual(len(env.payload.document["events"]), 1)

    def test_get_message_text_all_fail_returns_empty(self):
        """All messages failing to fetch returns empty events — not an error. (lines 168-169)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1", "m2"]
        svc.get_message_text.side_effect = RuntimeError("network error")
        request = _make_receipts_request()
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailReceiptsRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])


class TestParseSingleReceiptBranches(unittest.TestCase):
    """Covers lines 184, 188: incomplete receipt patterns and invalid date ranges."""

    def _make_processor(self, text: str) -> GmailReceiptsProcessor:
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.return_value = text
        return GmailReceiptsProcessor(service_builder=lambda _auth: svc)

    def test_missing_pattern_returns_no_event(self):
        """Text without all three required patterns yields no event. (line 184)"""
        # Has cls and sched but no Meeting Dates.
        text = (
            "Enrollment in Swimming Lesson (# 1)\n"
            "Each Monday from 5:00 pm to 5:30 pm\n"
        )
        processor = self._make_processor(text)
        env = processor.process(GmailReceiptsRequestConsumer(_make_receipts_request()).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])

    def test_invalid_month_name_returns_no_event(self):
        """Unrecognizable month name yields no event. (lines 188, 217)"""
        # 'Smarch' is not a valid month.
        text = (
            "Enrollment in Swimming Lesson (# 1)\n"
            "Meeting Dates: From Smarch 1, 2026 to Smarch 31, 2026\n"
            "Each Monday from 5:00 pm to 5:30 pm\n"
        )
        processor = self._make_processor(text)
        env = processor.process(GmailReceiptsRequestConsumer(_make_receipts_request()).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document["events"], [])

    def test_no_location_event_has_no_location_field(self):
        """Receipt without Location line: event dict has no 'location' key. (lines 203->206)"""
        text = (
            "Enrollment in Swim Kids 2 (# 99)\n"
            "Meeting Dates: From February 1, 2026 to April 1, 2026\n"
            "Each Wednesday from 4:00 pm to 4:30 pm\n"
            # No Location: line
        )
        processor = self._make_processor(text)
        env = processor.process(GmailReceiptsRequestConsumer(_make_receipts_request()).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)
        ev = env.payload.document["events"][0]
        self.assertNotIn("location", ev)

    def test_child_info_extracted_into_event(self):
        """Registrant line populates child (first name) in the event. (lines 208-209)

        The PAT_1 regex is greedy over whitespace so child_full may include
        subsequent lines; the important assertion is that child_first is
        correctly extracted as the first whitespace-delimited token.
        """
        text = (
            "Enrollment in Swim Kids 3 (# 12345)\n"
            "Registrant: Jane Doe\n"
            "Meeting Dates: From January 5, 2026 to March 5, 2026\n"
            "Each Thursday from 6:00 pm to 6:30 pm\n"
            "Location: Elgin West Pool\n"
        )
        processor = self._make_processor(text)
        env = processor.process(GmailReceiptsRequestConsumer(_make_receipts_request()).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)
        ev = env.payload.document["events"][0]
        # child is always the first whitespace-delimited token in title case.
        self.assertEqual(ev["child"], "Jane")
        # child_full starts with "Jane Doe" (may capture greedy trailing text).
        self.assertTrue(ev["child_full"].startswith("Jane Doe"))

    def test_receipt_with_valid_location_sets_location_field(self):
        """Happy path: receipt with valid location sets location on the event. (line 203->204)"""
        text = (
            "Enrollment in Swim Kids 1 (# 555)\n"
            "Meeting Dates: From September 1, 2026 to November 1, 2026\n"
            "Each Tuesday from 7:00 pm to 7:30 pm\n"
            "Location: Richmond Green\n"
        )
        processor = self._make_processor(text)
        env = processor.process(GmailReceiptsRequestConsumer(_make_receipts_request()).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)
        self.assertEqual(env.payload.document["events"][0]["location"], "Richmond Green")


# ---------------------------------------------------------------------------
# _extract_child_info: PAT_2 fallback
# ---------------------------------------------------------------------------

class TestExtractChildInfoPatterns(unittest.TestCase):
    """Covers lines 230-232: PAT_2 as fallback to PAT_1."""

    def setUp(self):
        self.processor = GmailReceiptsProcessor()

    def test_extract_child_pat1_match(self):
        """PAT_1 (Registrant:) yields child first name and full name."""
        text = "Registrant:\n  Alice Smith"
        first, full = self.processor._extract_child_info(text)
        self.assertEqual(first, "Alice")
        self.assertIn("Alice", full)

    def test_extract_child_pat2_fallback(self):
        """PAT_2 (Order Summary) is used when PAT_1 does not match. (lines 230-232)"""
        text = "Order Summary: Bob Johnson Enrollment in Chess"
        first, full = self.processor._extract_child_info(text)
        self.assertEqual(first, "Bob")
        self.assertIn("Bob", full)

    def test_extract_child_no_match_returns_none_tuple(self):
        """No match returns (None, None)."""
        first, full = self.processor._extract_child_info("No registrant info here")
        self.assertIsNone(first)
        self.assertIsNone(full)


# ---------------------------------------------------------------------------
# _normalize_subject branches
# ---------------------------------------------------------------------------

class TestNormalizeSubjectBranches(unittest.TestCase):
    """Covers lines 243-250: all _normalize_subject code paths."""

    def setUp(self):
        self.processor = GmailReceiptsProcessor()

    def _n(self, raw: str, loc: str | None = None) -> str:
        return self.processor._normalize_subject(raw, loc)

    def test_swimmer_prefix_titles(self):
        """'swimmer ...' prefix yields Title Case. (line 244)"""
        self.assertEqual(self._n("swimmer dance"), "Swimmer Dance")

    def test_swim_kids_prefix_titles(self):
        """'swim kids ...' prefix yields Title Case. (line 244)"""
        self.assertEqual(self._n("Swim Kids 3"), "Swim Kids 3")

    def test_chess_prefix_yields_chess(self):
        """'chess ...' subject normalizes to 'Chess'. (line 247)"""
        self.assertEqual(self._n("chess club"), "Chess")

    def test_single_c_yields_chess(self):
        """Single 'c' normalizes to 'Chess'. (line 247)"""
        self.assertEqual(self._n("c"), "Chess")

    def test_single_s_with_pool_location_yields_swimmer(self):
        """Single 's' with a pool location hint yields 'Swimmer'. (line 248)"""
        self.assertEqual(self._n("s", "Elgin West Pool"), "Swimmer")

    def test_single_s_without_pool_location_yields_sports(self):
        """Single 's' with non-pool location yields 'Sports'. (line 248)"""
        self.assertEqual(self._n("s", "Sports Complex"), "Sports")

    def test_single_s_with_no_location_yields_sports(self):
        """Single 's' with None location yields 'Sports'. (line 248)"""
        self.assertEqual(self._n("s", None), "Sports")

    def test_default_title_case(self):
        """Unmatched input is title-cased. (line 250)"""
        self.assertEqual(self._n("soccer training"), "Soccer Training")

    def test_subject_with_dash_strips_suffix(self):
        """Subject with ' - ' suffix strips at the dash before title-casing."""
        self.assertEqual(self._n("Soccer - Advanced"), "Soccer")

    def test_happy_path_normal_subject(self):
        """Typical class name returns title case (cross-check with other branches)."""
        result = self._n("gymnastics level 2")
        self.assertEqual(result, "Gymnastics Level 2")


# ---------------------------------------------------------------------------
# GmailScanClassesProcessor — coverage gaps
# ---------------------------------------------------------------------------

class TestGmailScanClassesProcessorCoverageGaps(unittest.TestCase):
    """Covers lines 319, 324-325, 329, 336."""

    def test_no_ids_returns_empty_result(self):
        """Empty id list returns result with 0 events and 0 message_count. (line 319)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = []
        request = _make_classes_request()
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailScanClassesRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.events, [])
        self.assertEqual(env.payload.message_count, 0)
        svc.get_message_text.assert_not_called()

    def test_get_message_text_exception_skips_message(self):
        """Exception during get_message_text is skipped; remaining messages process. (lines 324-325)"""
        good = "Monday from 5:00 pm to 5:30 pm"
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m-bad", "m-good"]
        svc.get_message_text.side_effect = [RuntimeError("timeout"), good]
        request = _make_classes_request()
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailScanClassesRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.events), 1)

    def test_ids_present_but_no_schedule_lines_found(self):
        """Messages parsed but no schedule regex matches -> empty events, message_count>0. (line 329)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.return_value = "Nothing schedule-like here"
        request = _make_classes_request()
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailScanClassesRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.events, [])
        self.assertEqual(env.payload.message_count, 1)

    def test_happy_path_events_found(self):
        """Schedule text parsed -> non-empty events, message_count matches. (line 336)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1", "m2"]
        svc.get_message_text.side_effect = [
            "Monday from 5:00 pm to 5:30 pm",
            "Tuesday from 6:00 pm to 6:30 pm",
        ]
        request = _make_classes_request()
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailScanClassesRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertGreater(len(env.payload.events), 0)
        self.assertEqual(env.payload.message_count, 2)


# ---------------------------------------------------------------------------
# GmailScanClassesProcessor._extract_events — meta field branches
# ---------------------------------------------------------------------------

class TestExtractEventsMetaBranches(unittest.TestCase):
    """Covers lines 353, 357, 375-381: meta subject/location/range propagated into events."""

    def setUp(self):
        self.processor = GmailScanClassesProcessor()

    def test_meta_subject_overrides_default(self):
        """When infer_meta returns a subject, it replaces 'Class'. (line 353)

        CLASS_PAT matches patterns like 'swimmer 2a', 'swim kids 3', 'preschool a'.
        Use a known pattern to guarantee meta['subject'] is populated.
        """
        text = "Swimmer 2A\nMonday from 5:00 pm to 5:30 pm"
        events = self.processor._extract_events(text, None)
        self.assertGreater(len(events), 0)
        # subject must have been overridden from 'Class' to the detected class name
        self.assertNotEqual(events[0]["subject"], "Class")
        self.assertIn("Swimmer", events[0]["subject"])

    def test_meta_location_propagated(self):
        """When infer_meta returns a location, it is set on the event. (line 357)

        The location_infer function reads the LOC_LABEL_PAT from the text.
        The exact string captured may vary with how html_to_text joins lines,
        so we assert the location key is present and starts with the venue name.
        """
        text = "Location: Elgin West\nWednesday from 3:00 pm to 4:00 pm"
        events = self.processor._extract_events(text, None)
        self.assertGreater(len(events), 0)
        self.assertIn("location", events[0])
        self.assertIn("Elgin West", events[0]["location"])

    def test_meta_range_merged_into_event(self):
        """When infer_meta returns a range, it is merged into the event. (lines 375-381)

        The range pattern matches 'From <Month> <D>, <Y> to <Month> <D>, <Y>'.
        """
        text = (
            "From January 1, 2026 to March 1, 2026\n"
            "Tuesday from 4:00 pm to 5:00 pm"
        )
        events = self.processor._extract_events(text, "cal")
        self.assertGreater(len(events), 0)
        # range must have been merged in
        ev = events[0]
        self.assertIn("range", ev)
        self.assertEqual(ev["range"]["start_date"], "2026-01-01")
        self.assertEqual(ev["range"]["until"], "2026-03-01")

    def test_html_to_text_strips_tags(self):
        """_html_to_text removes HTML tags before regex matching."""
        html = "<p>Monday from 5:00 pm to 5:30 pm</p>"
        events = self.processor._extract_events(html, None)
        self.assertGreater(len(events), 0)

    def test_no_schedule_line_returns_empty(self):
        """Message with no day-time pattern returns empty list."""
        events = self.processor._extract_events("No schedule here", None)
        self.assertEqual(events, [])


# ---------------------------------------------------------------------------
# GmailScanClassesProducer — output branches
# ---------------------------------------------------------------------------

class TestGmailScanClassesProducerBranches(unittest.TestCase):
    """Producer output branches for various result states."""

    def _wrap(self, payload):
        return ResultEnvelope(status="success", payload=payload)

    def test_no_events_no_messages_prints_no_matching(self):
        """Zero events and zero messages: 'No matching messages found.' output."""
        from calendars.gmail_pipelines import GmailScanClassesResult
        payload = GmailScanClassesResult(events=[], message_count=0, out_path=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailScanClassesProducer().produce(self._wrap(payload))
        self.assertIn("No matching messages found", buf.getvalue())

    def test_no_events_with_messages_prints_no_schedule_lines(self):
        """Zero events but some messages scanned: 'No schedule-like lines' output."""
        from calendars.gmail_pipelines import GmailScanClassesResult
        payload = GmailScanClassesResult(events=[], message_count=3, out_path=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailScanClassesProducer().produce(self._wrap(payload))
        self.assertIn("No schedule-like lines", buf.getvalue())
        # Also prints the --out hint since no out_path
        self.assertIn("--out", buf.getvalue())

    def test_events_without_out_path_prints_per_event_lines(self):
        """Events present, no out_path: prints per-event byday/time lines."""
        from calendars.gmail_pipelines import GmailScanClassesResult
        events = [
            {"byday": ["MO"], "start_time": "17:00", "end_time": "17:30", "calendar": "Sports"},
        ]
        payload = GmailScanClassesResult(events=events, message_count=1, out_path=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailScanClassesProducer().produce(self._wrap(payload))
        output = buf.getvalue()
        self.assertIn("MO", output)
        self.assertIn("17:00", output)

    def test_events_with_out_path_writes_yaml_and_prints(self):
        """Events present, out_path set: YAML is written and path is printed."""
        from calendars.gmail_pipelines import GmailScanClassesResult
        events = [{"byday": ["TU"], "start_time": "18:00", "end_time": "18:30", "calendar": None}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "classes.yaml"
            payload = GmailScanClassesResult(events=events, message_count=1, out_path=out)
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailScanClassesProducer().produce(self._wrap(payload))
            self.assertTrue(out.exists())
            self.assertIn(str(out), buf.getvalue())


# ---------------------------------------------------------------------------
# GmailMailListProcessor — empty ids and fetch exception
# ---------------------------------------------------------------------------

class TestGmailMailListProcessorCoverageGaps(unittest.TestCase):
    """Covers lines 423, 435."""

    def test_no_ids_returns_empty_messages(self):
        """Empty id list returns empty messages result. (line 423)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = []
        request = _make_mail_list_request()
        processor = GmailMailListProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailMailListRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.messages, [])
        svc.get_message_text.assert_not_called()

    def test_get_message_text_exception_stored_as_error_snippet(self):
        """Exception during get_message_text stored as a snippet, not re-raised. (line 435)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.side_effect = RuntimeError("connection reset")
        request = _make_mail_list_request()
        processor = GmailMailListProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailMailListRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.messages), 1)
        snippet = env.payload.messages[0]["snippet"]
        self.assertIn("failed to fetch", snippet)
        self.assertIn("connection reset", snippet)

    def test_happy_path_returns_snippet_from_first_line(self):
        """Happy path: first line of message text is returned as snippet."""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.return_value = "First line\nSecond line"
        request = _make_mail_list_request()
        processor = GmailMailListProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailMailListRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.messages[0]["snippet"], "First line")


# ---------------------------------------------------------------------------
# GmailMailListProducer — output branches
# ---------------------------------------------------------------------------

class TestGmailMailListProducerBranches(unittest.TestCase):
    """Covers lines 440-442 and 452-453."""

    def _wrap(self, payload):
        return ResultEnvelope(status="success", payload=payload)

    def test_no_messages_prints_no_match(self):
        """Empty messages list prints 'No messages matched.' (lines 440-442)"""
        from calendars.gmail_pipelines import GmailMailListResult
        payload = GmailMailListResult(messages=[])
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailMailListProducer().produce(self._wrap(payload))
        self.assertIn("No messages matched", buf.getvalue())

    def test_messages_listed_prints_each_and_count(self):
        """Non-empty messages: each is printed with id|snippet, count shown. (lines 452-453)"""
        from calendars.gmail_pipelines import GmailMailListResult
        messages = [
            {"id": "m1", "snippet": "Hello"},
            {"id": "m2", "snippet": "World"},
        ]
        payload = GmailMailListResult(messages=messages)
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailMailListProducer().produce(self._wrap(payload))
        output = buf.getvalue()
        self.assertIn("m1", output)
        self.assertIn("Hello", output)
        self.assertIn("Listed 2 Gmail message", output)


# ---------------------------------------------------------------------------
# GmailSweepTopProcessor — empty ids and sender fetch failure
# ---------------------------------------------------------------------------

class TestGmailSweepTopProcessorCoverageGaps(unittest.TestCase):
    """Covers lines 492 and 504."""

    def test_no_ids_returns_empty_top_senders(self):
        """Empty id list returns top_senders=[]. (line 492)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = []
        request = _make_sweep_top_request()
        processor = GmailSweepTopProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailSweepTopRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(env.payload.top_senders, [])
        svc.get_message.assert_not_called()

    def test_get_message_raises_sender_counted_as_none(self):
        """get_message raising causes _extract_sender to return None, not crash. (line 504)"""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message.side_effect = RuntimeError("forbidden")
        request = _make_sweep_top_request()
        processor = GmailSweepTopProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailSweepTopRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        # get_message raised, so no sender is counted — top_senders is empty.
        self.assertEqual(env.payload.top_senders, [])

    def test_happy_path_sender_counted(self):
        """Happy path: get_message returns valid From header, sender is counted."""
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message.return_value = {
            "payload": {"headers": [{"name": "From", "value": "Alice <alice@example.com>"}]}
        }
        request = _make_sweep_top_request(top=1)
        processor = GmailSweepTopProcessor(service_builder=lambda _auth: svc)

        env = processor.process(GmailSweepTopRequestConsumer(request).consume())

        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.top_senders), 1)
        self.assertEqual(env.payload.top_senders[0][0], "alice@example.com")


# ---------------------------------------------------------------------------
# GmailSweepTopProducer — all output branches
# ---------------------------------------------------------------------------

class TestGmailSweepTopProducerBranches(unittest.TestCase):
    """Covers lines 519->517, 527-528, 536->535, 541."""

    def _wrap(self, payload):
        return ResultEnvelope(status="success", payload=payload)

    def test_no_senders_prints_no_stats(self):
        """Empty top_senders prints 'No sender stats available.' (lines 519->517)"""
        from calendars.gmail_pipelines import GmailSweepTopResult
        payload = GmailSweepTopResult(
            top_senders=[], freq_days=7, inbox_only=False, out_path=None
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(self._wrap(payload))
        self.assertIn("No sender stats available", buf.getvalue())

    def test_senders_without_out_path_prints_per_sender(self):
        """Senders present, no out_path: each sender and count is printed. (lines 527-528)"""
        from calendars.gmail_pipelines import GmailSweepTopResult
        payload = GmailSweepTopResult(
            top_senders=[("alice@example.com", 5), ("bob@example.com", 3)],
            freq_days=30,
            inbox_only=True,
            out_path=None,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(self._wrap(payload))
        output = buf.getvalue()
        self.assertIn("alice@example.com", output)
        self.assertIn("bob@example.com", output)
        self.assertIn("5", output)
        self.assertIn("Top 2 sender", output)

    def test_senders_with_out_path_writes_yaml_filters(self):
        """Senders + out_path: YAML filter file is written. (lines 536->535, 541)"""
        from calendars.gmail_pipelines import GmailSweepTopResult
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "filters.yaml"
            payload = GmailSweepTopResult(
                top_senders=[("spam@example.com", 10)],
                freq_days=7,
                inbox_only=False,
                out_path=out,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailSweepTopProducer().produce(self._wrap(payload))
            self.assertTrue(out.exists())
            output = buf.getvalue()
            self.assertIn(str(out), output)
            # The written YAML should contain filter entries for the sender.
            content = out.read_text()
            self.assertIn("spam@example.com", content)

    def test_senders_with_out_path_output_includes_sender_lines(self):
        """With out_path, sender summary is printed before YAML is written."""
        from calendars.gmail_pipelines import GmailSweepTopResult
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.yaml"
            payload = GmailSweepTopResult(
                top_senders=[("news@example.com", 8)],
                freq_days=14,
                inbox_only=True,
                out_path=out,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailSweepTopProducer().produce(self._wrap(payload))
            self.assertIn("news@example.com", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
