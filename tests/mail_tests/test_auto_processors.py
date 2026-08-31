"""Tests for mail/auto/processors.py auto-categorization functionality."""

from __future__ import annotations

import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch, MagicMock

from mail.auto.processors import (
    classify_low_interest,
    AutoSummaryProcessor,
    AutoApplyProcessor,
)
from mail.utils.senders import is_protected_sender
from mail.auto.consumers import (
    AutoProposePayload,
    AutoSummaryPayload,
    AutoApplyPayload,
)
from tests.mail_tests.fixtures import make_args, make_message_with_headers as _make_message


class TestClassifyLowInterest(unittest.TestCase):
    """Tests for classify_low_interest function."""

    def test_returns_none_for_normal_message(self):
        msg = _make_message("m1", {"From": "friend@example.com", "Subject": "Hello"})
        result = classify_low_interest(msg)
        self.assertIsNone(result)

    def test_detects_list_unsubscribe_header(self):
        msg = _make_message(
            "m1",
            {
                "From": "newsletter@example.com",
                "Subject": "Weekly Update",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("list", result["reasons"])

    def test_detects_list_id_header(self):
        msg = _make_message(
            "m1",
            {
                "From": "list@example.com",
                "Subject": "Discussion",
                "List-Id": "<list.example.com>",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("list", result["reasons"])

    def test_detects_precedence_bulk(self):
        msg = _make_message(
            "m1",
            {
                "From": "bulk@example.com",
                "Subject": "Announcement",
                "Precedence": "bulk",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("bulk", result["reasons"])

    def test_detects_precedence_list(self):
        msg = _make_message(
            "m1",
            {
                "From": "list@example.com",
                "Subject": "Update",
                "Precedence": "list",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("bulk", result["reasons"])

    def test_detects_auto_submitted(self):
        msg = _make_message(
            "m1",
            {
                "From": "noreply@example.com",
                "Subject": "Notification",
                "Auto-Submitted": "auto-generated",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("auto-submitted", result["reasons"])

    def test_ignores_auto_submitted_no(self):
        msg = _make_message(
            "m1",
            {
                "From": "person@example.com",
                "Subject": "Hello",
                "Auto-Submitted": "no",
            },
        )
        result = classify_low_interest(msg)
        self.assertIsNone(result)

    def test_detects_category_promotions_label(self):
        msg = _make_message(
            "m1",
            {"From": "store@example.com", "Subject": "Check out our products"},
            label_ids=["INBOX", "CATEGORY_PROMOTIONS"],
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("category:promotions", result["reasons"])
        self.assertIn("Lists/Commercial", result["add"])

    def test_detects_category_forums_label(self):
        msg = _make_message(
            "m1",
            {"From": "forum@example.com", "Subject": "New post"},
            label_ids=["INBOX", "CATEGORY_FORUMS"],
        )
        result = classify_low_interest(msg)
        self.assertIsNotNone(result)
        self.assertIn("category:forums", result["reasons"])

    def test_detects_promo_keywords_in_subject(self):
        test_cases = [
            "Big Sale Today!",
            "50% off everything",
            "Best deal of the year",
            "Use promo code SAVE20",
            "Clearance event",
            "Free shipping on orders",
            "Your coupon inside",
        ]
        for subject in test_cases:
            msg = _make_message("m1", {"From": "store@example.com", "Subject": subject})
            result = classify_low_interest(msg)
            self.assertIsNotNone(result, f"Should detect promo in: {subject}")
            self.assertIn("promo-subject", result["reasons"])

    def test_assigns_commercial_label_for_promotions(self):
        msg = _make_message(
            "m1",
            {"From": "store@example.com", "Subject": "Sale today!"},
        )
        result = classify_low_interest(msg)
        self.assertIn("Lists/Commercial", result["add"])

    def test_assigns_newsletters_label_for_lists(self):
        msg = _make_message(
            "m1",
            {
                "From": "news@example.com",
                "Subject": "Weekly digest",
                "List-Unsubscribe": "<mailto:unsub@example.com>",
            },
        )
        result = classify_low_interest(msg)
        self.assertIn("Lists/Newsletters", result["add"])

    def test_removes_inbox_label(self):
        msg = _make_message(
            "m1",
            {"From": "list@example.com", "Subject": "Update", "Precedence": "bulk"},
        )
        result = classify_low_interest(msg)
        self.assertIn("INBOX", result["remove"])

    def test_includes_message_metadata(self):
        msg = _make_message(
            "m1",
            {"From": "sender@example.com", "Subject": "Promo inside"},
            internal_date=1700000000000,
        )
        result = classify_low_interest(msg)
        self.assertEqual(result["from"], "sender@example.com")
        self.assertEqual(result["subject"], "Promo inside")


class TestIsProtected(unittest.TestCase):
    """Tests for is_protected_sender."""

    def test_matches_exact_email(self):
        result = is_protected_sender("friend@example.com", ["friend@example.com"])
        self.assertTrue(result)

    def test_matches_domain_pattern(self):
        result = is_protected_sender("anyone@company.com", ["@company.com"])
        self.assertTrue(result)

    def test_extracts_email_from_display_name(self):
        result = is_protected_sender("John Doe <john@protected.com>", ["john@protected.com"])
        self.assertTrue(result)

    def test_case_insensitive(self):
        result = is_protected_sender("JOHN@Example.COM", ["john@example.com"])
        self.assertTrue(result)

    def test_no_match_returns_false(self):
        result = is_protected_sender("other@example.com", ["protected@example.com"])
        self.assertFalse(result)

    def test_empty_patterns_returns_false(self):
        result = is_protected_sender("anyone@example.com", [])
        self.assertFalse(result)

    def test_skips_empty_patterns(self):
        result = is_protected_sender("test@example.com", ["", None, "test@example.com"])
        self.assertTrue(result)


class TestAutoSummaryProcessor(unittest.TestCase):
    """Tests for AutoSummaryProcessor."""

    def test_summarizes_proposal(self):
        proposal = {
            "messages": [
                {"id": "m1", "reasons": ["list", "bulk"], "add": ["Lists/Newsletters"]},
                {"id": "m2", "reasons": ["list"], "add": ["Lists/Newsletters"]},
                {"id": "m3", "reasons": ["promo-subject"], "add": ["Lists/Commercial"]},
            ]
        }
        payload = AutoSummaryPayload(proposal=proposal)
        processor = AutoSummaryProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        result = envelope.payload
        self.assertEqual(result.message_count, 3)
        self.assertEqual(result.reasons["list"], 2)
        self.assertEqual(result.reasons["bulk"], 1)
        self.assertEqual(result.reasons["promo-subject"], 1)
        self.assertEqual(result.label_adds["Lists/Newsletters"], 2)
        self.assertEqual(result.label_adds["Lists/Commercial"], 1)

    def test_handles_empty_proposal(self):
        payload = AutoSummaryPayload(proposal={"messages": []})
        processor = AutoSummaryProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.message_count, 0)
        self.assertEqual(envelope.payload.reasons, {})

    def test_handles_missing_messages_key(self):
        payload = AutoSummaryPayload(proposal={})
        processor = AutoSummaryProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.message_count, 0)


@dataclass
class FakeAutoClient:
    """Fake Gmail client for auto pipeline tests."""

    labels: list[dict[str, str]] = field(default_factory=list)
    message_ids_by_query: dict[str, list[str]] = field(default_factory=dict)
    messages: dict[str, dict] = field(default_factory=dict)

    # Track mutations
    modified_batches: list[tuple] = field(default_factory=list)

    def authenticate(self) -> None:
        """No-op: test fixture does not require authentication."""
        pass

    def get_label_id_map(self) -> dict[str, str]:
        return {lab["name"]: lab["id"] for lab in self.labels}

    def list_message_ids(
        self,
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_pages: int = 1,
        page_size: int = 500,
    ) -> list[str]:
        q = (query or "").lower()
        for pattern, ids in self.message_ids_by_query.items():
            if pattern.lower() in q:
                return ids
        return []

    def get_messages_metadata(self, ids: list[str], use_cache: bool = True) -> list[dict]:
        return [self.messages.get(mid, {"id": mid}) for mid in ids]

    def batch_modify_messages(
        self,
        ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> None:
        self.modified_batches.append((list(ids), list(add_label_ids or []), list(remove_label_ids or [])))


def _make_auto_context(client: FakeAutoClient):
    """Create a MailContext with auto client."""
    from mail.context import MailContext

    args = make_args()
    ctx = MailContext.from_args(args)
    ctx.gmail_client = client
    return ctx


class TestAutoApplyProcessor(unittest.TestCase):
    """Tests for AutoApplyProcessor."""

    def test_applies_label_changes(self):
        client = FakeAutoClient(
            labels=[
                {"id": "LBL_NEWS", "name": "Lists/Newsletters"},
                {"id": "LBL_COMM", "name": "Lists/Commercial"},
            ]
        )
        ctx = _make_auto_context(client)

        proposal = {
            "messages": [
                {"id": "m1", "add": ["Lists/Newsletters"], "remove": ["INBOX"], "ts": 1000},
                {"id": "m2", "add": ["Lists/Newsletters"], "remove": ["INBOX"], "ts": 1000},
                {"id": "m3", "add": ["Lists/Commercial"], "remove": ["INBOX"], "ts": 1000},
            ]
        }

        # Mock the AppLogger to avoid file I/O
        with patch("mail.applog.AppLogger") as MockLogger:
            mock_logger = MagicMock()
            mock_logger.start.return_value = "session_id"
            MockLogger.return_value = mock_logger

            payload = AutoApplyPayload(
                context=ctx,
                proposal=proposal,
                batch_size=10,
                dry_run=False,
                log_path="/dev/null",
            )
            processor = AutoApplyProcessor()
            envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.total_modified, 3)
        self.assertFalse(envelope.payload.dry_run)
        # Should have batched by label combo
        self.assertGreaterEqual(len(client.modified_batches), 1)

    def test_dry_run_does_not_modify(self):
        client = FakeAutoClient(
            labels=[{"id": "LBL_NEWS", "name": "Lists/Newsletters"}]
        )
        ctx = _make_auto_context(client)

        proposal = {
            "messages": [
                {"id": "m1", "add": ["Lists/Newsletters"], "remove": ["INBOX"], "ts": 1000},
            ]
        }

        with patch("mail.applog.AppLogger") as MockLogger:
            mock_logger = MagicMock()
            mock_logger.start.return_value = "session_id"
            MockLogger.return_value = mock_logger

            payload = AutoApplyPayload(
                context=ctx,
                proposal=proposal,
                batch_size=10,
                dry_run=True,
                log_path="/dev/null",
            )
            processor = AutoApplyProcessor()
            envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.total_modified, 1)
        self.assertTrue(envelope.payload.dry_run)
        # No actual modifications in dry run
        self.assertEqual(len(client.modified_batches), 0)

    def test_respects_cutoff_days(self):
        client = FakeAutoClient(
            labels=[{"id": "LBL_NEWS", "name": "Lists/Newsletters"}]
        )
        ctx = _make_auto_context(client)

        now = int(time.time())
        old_ts = now - 100 * 86400  # 100 days ago
        recent_ts = now - 5 * 86400  # 5 days ago

        proposal = {
            "messages": [
                {"id": "m_old", "add": ["Lists/Newsletters"], "remove": ["INBOX"], "ts": old_ts},
                {"id": "m_recent", "add": ["Lists/Newsletters"], "remove": ["INBOX"], "ts": recent_ts},
            ]
        }

        with patch("mail.applog.AppLogger") as MockLogger:
            mock_logger = MagicMock()
            mock_logger.start.return_value = "session_id"
            MockLogger.return_value = mock_logger

            payload = AutoApplyPayload(
                context=ctx,
                proposal=proposal,
                cutoff_days=30,  # Only process messages older than 30 days
                batch_size=10,
                dry_run=False,
                log_path="/dev/null",
            )
            processor = AutoApplyProcessor()
            envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        # Only old message should be processed (recent is newer than cutoff)
        self.assertEqual(envelope.payload.total_modified, 1)

    def test_batches_by_label_combination(self):
        client = FakeAutoClient(
            labels=[
                {"id": "LBL_A", "name": "LabelA"},
                {"id": "LBL_B", "name": "LabelB"},
            ]
        )
        ctx = _make_auto_context(client)

        proposal = {
            "messages": [
                {"id": "m1", "add": ["LabelA"], "remove": ["INBOX"], "ts": 1000},
                {"id": "m2", "add": ["LabelA"], "remove": ["INBOX"], "ts": 1000},
                {"id": "m3", "add": ["LabelB"], "remove": ["INBOX"], "ts": 1000},
            ]
        }

        with patch("mail.applog.AppLogger") as MockLogger:
            mock_logger = MagicMock()
            mock_logger.start.return_value = "session_id"
            MockLogger.return_value = mock_logger

            payload = AutoApplyPayload(
                context=ctx,
                proposal=proposal,
                batch_size=10,
                dry_run=False,
                log_path="/dev/null",
            )
            processor = AutoApplyProcessor()
            envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        # Should have 2 groups: LabelA (2 msgs) and LabelB (1 msg)
        self.assertEqual(len(envelope.payload.groups), 2)


class TestAutoSummaryProcessorSadPath(unittest.TestCase):
    """Sad-path coverage for AutoSummaryProcessor SafeProcessor wrapping."""

    def test_raises_wraps_as_error_envelope(self):
        """A non-dict proposal that raises on access is wrapped as ResultEnvelope error."""
        # AutoSummaryProcessor._process_safe calls payload.proposal.get("messages") —
        # passing a non-dict proposal triggers AttributeError.
        payload = AutoSummaryPayload(proposal="not-a-dict")
        processor = AutoSummaryProcessor()
        envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIsNotNone(envelope.diagnostics)
        self.assertIsInstance(envelope.diagnostics.get("message"), str)
        self.assertIsNone(envelope.payload)


class TestAutoApplyProcessorSadPath(unittest.TestCase):
    """Sad-path coverage for AutoApplyProcessor SafeProcessor wrapping."""

    def test_client_exception_wraps_in_error_envelope(self):
        """A client failure inside _process_safe is wrapped as error envelope."""
        from mail.auto.consumers import AutoApplyPayload
        from unittest.mock import MagicMock

        # Mock context whose get_gmail_client() raises
        mock_ctx = MagicMock()
        mock_ctx.get_gmail_client.return_value.authenticate.side_effect = RuntimeError(
            "auth failed"
        )

        with patch("mail.applog.AppLogger") as MockLogger:
            mock_logger = MagicMock()
            mock_logger.start.return_value = "session_id"
            MockLogger.return_value = mock_logger

            payload = AutoApplyPayload(
                context=mock_ctx,
                proposal={"messages": [{"id": "m1", "add": ["Label"], "remove": [], "ts": 1000}]},
                batch_size=10,
                dry_run=False,
                log_path="/dev/null",
            )
            processor = AutoApplyProcessor()
            envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIn("auth failed", envelope.diagnostics.get("message", ""))
        self.assertIsNone(envelope.payload)
        mock_ctx.get_gmail_client.assert_called_once()


class TestAutoProposeProcessor(unittest.TestCase):
    """Tests for AutoProposeProcessor — happy and sad paths.

    Network calls are fully stubbed; no real Gmail credentials are used.
    """

    def _make_propose_payload(self, tmpdir: str, client) -> "AutoProposePayload":
        """Build an AutoProposePayload with a stub context and temp output path."""
        from tests.mail_tests.fixtures import FakeMailContext

        ctx = FakeMailContext(gmail_client=client)
        return AutoProposePayload(
            context=ctx,
            out_path=Path(tmpdir) / "proposal.json",
            days=7,
            pages=1,
            protect=[],
            log_path="/dev/null",
        )

    def test_happy_path_writes_proposal_file(self):
        """AutoProposeProcessor writes a proposal JSON file on success."""
        import json
        import tempfile

        # A promo message that classify_low_interest will flag.
        promo_msg = _make_message(
            "m1",
            {"From": "store@example.com", "Subject": "Big Sale Today"},
        )
        # A normal message that should be filtered out.
        normal_msg = _make_message(
            "m2",
            {"From": "friend@example.com", "Subject": "Lunch?"},
        )

        client = FakeAutoClient(
            labels=[],
            message_ids_by_query={"in:inbox": ["m1", "m2"]},
            messages={"m1": promo_msg, "m2": normal_msg},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = self._make_propose_payload(tmpdir, client)

            with (
                patch("mail.utils.gmail_ops.fetch_messages_with_metadata") as mock_fetch,
                patch("mail.applog.AppLogger") as MockLogger,
            ):
                mock_fetch.return_value = (["m1", "m2"], [promo_msg, normal_msg])
                mock_logger = MagicMock()
                mock_logger.start.return_value = "sid"
                MockLogger.return_value = mock_logger

                from mail.auto.processors import AutoProposeProcessor

                processor = AutoProposeProcessor()
                envelope = processor.process(payload)

            self.assertTrue(envelope.ok())
            result = envelope.payload
            self.assertEqual(result.total_considered, 2)
            self.assertEqual(result.selected_count, 1)
            self.assertIn("in:inbox", result.query)
            self.assertTrue(payload.out_path.exists())

            doc = json.loads(payload.out_path.read_text())
            self.assertEqual(doc["counts"]["selected"], 1)
            self.assertEqual(len(doc["messages"]), 1)
            mock_fetch.assert_called_once()

    def test_sad_path_client_error_wraps_in_error_envelope(self):
        """A client failure inside AutoProposeProcessor._process_safe surfaces as error envelope."""
        import tempfile
        from tests.mail_tests.fixtures import FakeMailContext

        bad_client = MagicMock()
        bad_client.authenticate.side_effect = RuntimeError("no credentials")
        ctx = FakeMailContext(gmail_client=bad_client)

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = AutoProposePayload(
                context=ctx,
                out_path=Path(tmpdir) / "proposal.json",
                days=7,
                pages=1,
                log_path="/dev/null",
            )

            with patch("mail.applog.AppLogger") as MockLogger:
                mock_logger = MagicMock()
                mock_logger.start.return_value = "sid"
                MockLogger.return_value = mock_logger

                from mail.auto.processors import AutoProposeProcessor

                processor = AutoProposeProcessor()
                envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIn("no credentials", envelope.diagnostics.get("message", ""))
        self.assertIsNone(envelope.payload)
        bad_client.authenticate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
