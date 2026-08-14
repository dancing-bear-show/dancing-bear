"""Tests for mail/labels/commands_doctor.py.

Covers the uncovered branches: _print_doctor_report, _redirect_imap_labels,
run_labels_doctor, _prune_one_label, run_labels_prune_empty, run_labels_learn,
_apply_one_suggestion, _maybe_sweep_after_suggestions, run_labels_delete,
_sweep_one_parent, run_labels_sweep_parents.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import (
    FakeGmailClient,
    make_args,
    make_user_label,
    make_label_with_visibility,
)


# ---------------------------------------------------------------------------
# Local extension: add list_labels(use_cache, ttl) and headers_to_dict
# ---------------------------------------------------------------------------


class ExtendedFakeGmailClient(FakeGmailClient):
    """FakeGmailClient extended with list_labels keyword args and headers_to_dict."""

    def list_labels(self, use_cache: bool = False, ttl: int = 300):  # NOSONAR
        return list(self.labels)

    @staticmethod
    def headers_to_dict(msg: dict) -> dict:
        return msg.get("_headers", {})


# ---------------------------------------------------------------------------
# _print_doctor_report (lines 9-20)
# ---------------------------------------------------------------------------


class TestPrintDoctorReport(unittest.TestCase):
    """Tests for _print_doctor_report."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _print_doctor_report
        cls.print_report = staticmethod(_print_doctor_report)

    def _make_info(self, **overrides) -> dict:
        base = {
            "total": 10,
            "duplicates": [],
            "max_depth": 2,
            "top_counts": {"Work": 3},
            "vis_label": {"labelShow": 8},
            "vis_message": {"show": 8},
            "imapish": [],
            "unset_visibility": [],
        }
        base.update(overrides)
        return base

    def test_prints_total(self):
        with capture_stdout() as buf:
            self.print_report(self._make_info(total=42))
        self.assertIn("42", buf.getvalue())

    def test_prints_duplicates_with_names(self):
        info = self._make_info(duplicates=["Dup1", "Dup2"])
        with capture_stdout() as buf:
            self.print_report(info)
        out = buf.getvalue()
        self.assertIn("Dup1", out)
        self.assertIn("Dup2", out)

    def test_prints_no_duplicates(self):
        with capture_stdout() as buf:
            self.print_report(self._make_info(duplicates=[]))
        self.assertIn("Duplicates: 0", buf.getvalue())

    def test_prints_imap_labels_with_names(self):
        info = self._make_info(imapish=["IMAP/Folder", "[Gmail]/Trash"])
        with capture_stdout() as buf:
            self.print_report(info)
        out = buf.getvalue()
        self.assertIn("IMAP/Folder", out)
        self.assertIn("[Gmail]/Trash", out)

    def test_prints_imap_labels_empty(self):
        with capture_stdout() as buf:
            self.print_report(self._make_info(imapish=[]))
        self.assertIn("IMAP-style labels: 0", buf.getvalue())

    def test_prints_unset_visibility_count(self):
        with capture_stdout() as buf:
            self.print_report(self._make_info(unset_visibility=["A", "B", "C"]))
        self.assertIn("Unset visibility count: 3", buf.getvalue())


# ---------------------------------------------------------------------------
# _redirect_imap_labels (lines 51-78)
# ---------------------------------------------------------------------------


class TestRedirectImapLabels(unittest.TestCase):
    """Tests for _redirect_imap_labels."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _redirect_imap_labels
        cls.redirect = staticmethod(_redirect_imap_labels)

    def test_no_specs_returns_zero(self):
        client = ExtendedFakeGmailClient()
        with capture_stdout():
            result = self.redirect(client, [])
        self.assertEqual(result, 0)

    def test_invalid_spec_no_equals_returns_zero(self):
        client = ExtendedFakeGmailClient()
        with capture_stdout():
            result = self.redirect(client, ["NoEqualsSign"])
        self.assertEqual(result, 0)

    def test_skips_missing_old_label(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("NewLabel", "NEW_ID"),
        ])
        with capture_stdout() as buf:
            result = self.redirect(client, ["MissingOld=NewLabel"])
        self.assertEqual(result, 0)
        self.assertIn("Skip redirect", buf.getvalue())

    def test_skips_when_ensure_label_returns_empty(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("OldLabel", "OLD_ID"),
        ])
        client.ensure_label = MagicMock(return_value="")
        with capture_stdout() as buf:
            result = self.redirect(client, ["OldLabel=MissingNew"])
        self.assertEqual(result, 0)
        self.assertIn("Skip redirect", buf.getvalue())

    def test_redirects_messages_and_returns_count(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("OldLabel", "OLD_ID"),
            make_user_label("NewLabel", "NEW_ID"),
        ])
        client.list_message_ids = MagicMock(return_value=["m1", "m2"])
        with patch("mail.utils.batch.apply_in_chunks") as mock_apply, \
                capture_stdout() as buf:
            result = self.redirect(client, ["OldLabel=NewLabel"])
        self.assertEqual(result, 1)
        mock_apply.assert_called_once()
        self.assertIn("Redirected", buf.getvalue())

    def test_creates_label_when_new_is_absent(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("OldLabel", "OLD_ID"),
        ])
        client.list_message_ids = MagicMock(return_value=["m1"])
        with patch("mail.utils.batch.apply_in_chunks"), capture_stdout():
            result = self.redirect(client, ["OldLabel=BrandNewLabel"])
        self.assertEqual(result, 1)
        names = [lab["name"] for lab in client.labels]
        self.assertIn("BrandNewLabel", names)


# ---------------------------------------------------------------------------
# run_labels_doctor (lines 94-114)
# ---------------------------------------------------------------------------


class TestRunLabelsDoctor(unittest.TestCase):
    """Tests for run_labels_doctor."""

    def _analyze_stub(self):
        return {
            "total": 2,
            "duplicates": [],
            "max_depth": 1,
            "top_counts": {},
            "vis_label": {},
            "vis_message": {},
            "imapish": [],
            "unset_visibility": [],
        }

    def _run_doctor(self, labels, **kwargs):
        client = ExtendedFakeGmailClient(labels=labels)
        args = make_args(
            set_visibility=kwargs.get("set_visibility", False),
            imap_redirect=kwargs.get("imap_redirect", None),
            imap_delete=kwargs.get("imap_delete", None),
            use_cache=False,
            cache_ttl=300,
        )
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
                patch("mail.labels.commands_plan._analyze_labels",
                      return_value=self._analyze_stub()), \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_doctor
            rc = run_labels_doctor(args)
        return rc, buf.getvalue(), client

    def test_happy_path_returns_zero(self):
        rc, out, _ = self._run_doctor([make_user_label("Work", "L1")])
        self.assertEqual(rc, 0)
        self.assertIn("Total labels", out)

    def test_set_visibility_updates_labels(self):
        labels = [make_user_label("Work", "L1")]  # missing visibility fields
        rc, out, _ = self._run_doctor(labels, set_visibility=True)
        self.assertEqual(rc, 0)
        self.assertIn("Updated visibility", out)
        self.assertIn("Applied 1 change", out)

    def test_no_changes_does_not_print_applied(self):
        labels = [make_label_with_visibility("Work", "L1")]
        rc, out, _ = self._run_doctor(labels, set_visibility=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("Applied", out)

    def test_imap_delete_removes_label(self):
        labels = [make_user_label("IMAP/Folder", "L1")]
        rc, out, _ = self._run_doctor(labels, imap_delete=["IMAP/Folder"])
        self.assertEqual(rc, 0)
        self.assertIn("Deleted label", out)
        self.assertIn("Applied 1 change", out)

    def test_imap_redirect_delegates_to_redirect_fn(self):
        labels = [
            make_user_label("OldLabel", "OLD_ID"),
            make_user_label("NewLabel", "NEW_ID"),
        ]
        client = ExtendedFakeGmailClient(labels=labels)
        args = make_args(
            set_visibility=False,
            imap_redirect=["OldLabel=NewLabel"],
            imap_delete=None,
            use_cache=False,
            cache_ttl=300,
        )
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
                patch("mail.labels.commands_plan._analyze_labels",
                      return_value=self._analyze_stub()), \
                patch("mail.labels.commands_doctor._redirect_imap_labels",
                      return_value=2) as mock_redir, \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_doctor
            rc = run_labels_doctor(args)
        self.assertEqual(rc, 0)
        mock_redir.assert_called_once_with(client, ["OldLabel=NewLabel"])
        self.assertIn("Applied 2 change", buf.getvalue())


# ---------------------------------------------------------------------------
# _prune_one_label (lines 138-148)
# ---------------------------------------------------------------------------


class TestPruneOneLabel(unittest.TestCase):
    """Tests for _prune_one_label."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _prune_one_label
        cls.prune = staticmethod(_prune_one_label)

    def test_dry_run_does_not_delete(self):
        client = FakeGmailClient(labels=[make_user_label("Empty", "L1")])
        lab = make_user_label("Empty", "L1")
        with capture_stdout() as buf:
            result = self.prune(client, lab, dry_run=True, sleep_s=0.0)
        self.assertFalse(result)
        self.assertIn("Would delete", buf.getvalue())
        self.assertEqual(len(client.labels), 1)

    def test_live_run_deletes_label(self):
        client = FakeGmailClient(labels=[make_user_label("Empty", "L1")])
        lab = make_user_label("Empty", "L1")
        with patch("time.sleep"), capture_stdout():
            result = self.prune(client, lab, dry_run=False, sleep_s=0.0)
        self.assertTrue(result)
        self.assertEqual(len(client.labels), 0)

    def test_sleep_called_when_sleep_s_positive(self):
        client = FakeGmailClient(labels=[make_user_label("Empty", "L1")])
        lab = make_user_label("Empty", "L1")
        with patch("time.sleep") as mock_sleep, capture_stdout():
            self.prune(client, lab, dry_run=False, sleep_s=0.5)
        mock_sleep.assert_called_once_with(0.5)

    def test_returns_false_when_delete_fails_all_retries(self):
        client = MagicMock()
        client.delete_label.side_effect = Exception("API error")
        lab = make_user_label("Empty", "L1")
        with patch("time.sleep"), capture_stdout():
            result = self.prune(client, lab, dry_run=False, sleep_s=0.0)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# run_labels_prune_empty (lines 151-171)
# ---------------------------------------------------------------------------


class TestRunLabelsPruneEmpty(unittest.TestCase):
    """Tests for run_labels_prune_empty."""

    def _run_prune(self, labels, dry_run=False, limit=0, sleep_sec=0.0):
        client = FakeGmailClient(labels=labels)
        args = make_args(dry_run=dry_run, limit=limit, sleep_sec=sleep_sec)
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
                patch("time.sleep"), \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_prune_empty
            rc = run_labels_prune_empty(args)
        return rc, buf.getvalue(), client

    def test_deletes_empty_user_labels(self):
        labels = [
            make_user_label("Empty1", "L1", messages=0),
            make_user_label("HasMessages", "L2", messages=5),
        ]
        rc, out, client = self._run_prune(labels)
        self.assertEqual(rc, 0)
        self.assertIn("Prune complete", out)
        self.assertIn("Deleted: 1", out)

    def test_dry_run_does_not_delete(self):
        labels = [make_user_label("Empty1", "L1", messages=0)]
        rc, out, client = self._run_prune(labels, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertIn("Would delete", out)
        self.assertIn("Deleted: 0", out)
        self.assertEqual(len(client.labels), 1)

    def test_limit_caps_deleted_count(self):
        labels = [
            make_user_label("E1", "L1", messages=0),
            make_user_label("E2", "L2", messages=0),
            make_user_label("E3", "L3", messages=0),
        ]
        rc, out, _ = self._run_prune(labels, limit=2)
        self.assertEqual(rc, 0)
        self.assertIn("Deleted: 2", out)

    def test_no_empty_labels_produces_zero_deleted(self):
        labels = [make_user_label("Full", "L1", messages=10)]
        rc, out, _ = self._run_prune(labels)
        self.assertEqual(rc, 0)
        self.assertIn("Deleted: 0", out)


# ---------------------------------------------------------------------------
# run_labels_learn (lines 250-294)
# ---------------------------------------------------------------------------


class TestRunLabelsLearn(unittest.TestCase):
    """Tests for run_labels_learn."""

    def _make_learn_args(self, out_path, days=30, min_count=5, protect=None,
                         only_inbox=False):
        return make_args(
            credentials="cred.json",
            token="tok.json",  # noqa: S106  # nosec B106 - test file path
            cache=None,
            days=days,
            min_count=min_count,
            protect=protect or [],
            only_inbox=only_inbox,
            out=out_path,
        )

    def _run_learn(self, messages, args):
        client = ExtendedFakeGmailClient()
        client.list_message_ids = MagicMock(return_value=[m["id"] for m in messages])
        client.get_messages_metadata = MagicMock(return_value=messages)
        client.headers_to_dict = MagicMock(side_effect=lambda m: m.get("_headers", {}))

        with patch("mail.config_resolver.resolve_paths_profile",
                   return_value=("cred.json", "tok.json")), \
                patch("mail.gmail_api.GmailClient", return_value=client), \
                patch("mail.utils.filters.build_gmail_query", return_value="in:inbox"), \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_learn
            rc = run_labels_learn(args)
        return rc, buf.getvalue()

    def test_promotions_label_suggestion_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "suggestions.yaml")
            msgs = [
                {"id": "m1", "_headers": {"from": "promo@shop.com"},
                 "labelIds": ["CATEGORY_PROMOTIONS"]},
                {"id": "m2", "_headers": {"from": "promo@shop.com"},
                 "labelIds": ["CATEGORY_PROMOTIONS"]},
            ]
            args = self._make_learn_args(out_path, min_count=1)
            rc, out = self._run_learn(msgs, args)
        self.assertEqual(rc, 0)
        self.assertIn("suggestions", out)

    def test_below_min_count_produces_zero_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "suggestions.yaml")
            msgs = [
                {"id": "m1", "_headers": {"from": "promo@shop.com"},
                 "labelIds": ["CATEGORY_PROMOTIONS"]},
            ]
            args = self._make_learn_args(out_path, min_count=999)
            rc, out = self._run_learn(msgs, args)
        self.assertEqual(rc, 0)
        self.assertIn("0 suggestions", out)

    def test_protected_sender_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "suggestions.yaml")
            msgs = [
                {"id": f"m{i}", "_headers": {"from": "promo@protected.com"},
                 "labelIds": ["CATEGORY_PROMOTIONS"]}
                for i in range(3)
            ]
            args = self._make_learn_args(out_path, min_count=1, protect=["@protected.com"])
            rc, out = self._run_learn(msgs, args)
        self.assertEqual(rc, 0)
        self.assertIn("0 suggestions", out)

    def test_domain_with_list_unsubscribe_header_gets_newsletter_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "suggestions.yaml")
            msgs = [
                {"id": f"m{i}", "_headers": {"from": "news@letters.com",
                                             "list-unsubscribe": "<url>"},
                 "labelIds": []}
                for i in range(3)
            ]
            args = self._make_learn_args(out_path, min_count=1)
            rc, out = self._run_learn(msgs, args)
        self.assertEqual(rc, 0)
        self.assertIn("1 suggestions", out)

    def test_domain_without_hints_produces_no_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "suggestions.yaml")
            msgs = [
                {"id": f"m{i}", "_headers": {"from": f"user{i}@plain.com"},
                 "labelIds": []}
                for i in range(5)
            ]
            args = self._make_learn_args(out_path, min_count=1)
            rc, out = self._run_learn(msgs, args)
        self.assertEqual(rc, 0)
        self.assertIn("0 suggestions", out)


# ---------------------------------------------------------------------------
# _apply_one_suggestion (lines 297-313)
# ---------------------------------------------------------------------------


class TestApplyOneSuggestion(unittest.TestCase):
    """Tests for _apply_one_suggestion."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _apply_one_suggestion
        cls.apply = staticmethod(_apply_one_suggestion)

    def test_missing_domain_returns_false(self):
        client = FakeGmailClient()
        result = self.apply(client, {"label": "Lists/Commercial"}, dry_run=False)
        self.assertFalse(result)

    def test_missing_label_returns_false(self):
        client = FakeGmailClient()
        result = self.apply(client, {"domain": "example.com"}, dry_run=False)
        self.assertFalse(result)

    def test_dry_run_prints_would_create_and_returns_true(self):
        client = FakeGmailClient()
        with patch("mail.utils.filters.action_to_label_changes",
                   return_value=(["LBL_Lists"], [])), \
                capture_stdout() as buf:
            result = self.apply(
                client,
                {"domain": "shop.com", "label": "Lists/Commercial"},
                dry_run=True,
            )
        self.assertTrue(result)
        self.assertIn("Would create", buf.getvalue())
        self.assertEqual(len(client.created_filters), 0)

    def test_live_run_creates_filter_and_returns_true(self):
        client = FakeGmailClient()
        with patch("mail.utils.filters.action_to_label_changes",
                   return_value=(["LBL_Lists"], [])), \
                capture_stdout() as buf:
            result = self.apply(
                client,
                {"domain": "shop.com", "label": "Lists/Commercial"},
                dry_run=False,
            )
        self.assertTrue(result)
        self.assertIn("Created rule", buf.getvalue())
        self.assertEqual(len(client.created_filters), 1)


# ---------------------------------------------------------------------------
# _maybe_sweep_after_suggestions (lines 316-329)
# ---------------------------------------------------------------------------


class TestMaybeSweepAfterSuggestions(unittest.TestCase):
    """Tests for _maybe_sweep_after_suggestions."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _maybe_sweep_after_suggestions
        cls.maybe_sweep = staticmethod(_maybe_sweep_after_suggestions)

    def test_no_sweep_days_does_not_call_run_filters_sweep(self):
        args = make_args(sweep_days=None)
        with patch("mail.filters.commands.run_filters_sweep") as mock_sweep:
            self.maybe_sweep(args, dry_run=False)
        mock_sweep.assert_not_called()

    def test_sweep_days_calls_run_filters_sweep_with_correct_days(self):
        args = make_args(
            sweep_days=7,
            credentials="cred.json",
            token="tok.json",  # noqa: S106  # nosec B106 - test file path
            cache=None,
            config="cfg.yaml",
            pages=2,
            batch_size=50,
        )
        with patch("mail.filters.commands.run_filters_sweep") as mock_sweep, \
                capture_stdout():
            self.maybe_sweep(args, dry_run=True)
        mock_sweep.assert_called_once()
        called_ns = mock_sweep.call_args[0][0]
        self.assertEqual(called_ns.days, 7)
        self.assertFalse(called_ns.only_inbox)
        self.assertTrue(called_ns.dry_run)


# ---------------------------------------------------------------------------
# run_labels_delete (lines 368-382)
# ---------------------------------------------------------------------------


class TestRunLabelsDelete(unittest.TestCase):
    """Tests for run_labels_delete."""

    def _run_delete(self, labels, name):
        client = ExtendedFakeGmailClient(labels=labels)
        args = make_args(name=name)
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_delete
            rc = run_labels_delete(args)
        return rc, buf.getvalue(), client

    def test_deletes_existing_label_returns_zero(self):
        labels = [make_user_label("ToDelete", "L1")]
        rc, out, client = self._run_delete(labels, "ToDelete")
        self.assertEqual(rc, 0)
        self.assertIn("Deleted label", out)
        self.assertEqual(len(client.labels), 0)

    def test_returns_one_when_label_not_found(self):
        rc, out, _ = self._run_delete([], "Missing")
        self.assertEqual(rc, 1)
        self.assertIn("Label not found", out)


# ---------------------------------------------------------------------------
# _sweep_one_parent (lines 385-406)
# ---------------------------------------------------------------------------


class TestSweepOneParent(unittest.TestCase):
    """Tests for _sweep_one_parent."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands_doctor import _sweep_one_parent
        cls.sweep_one = staticmethod(_sweep_one_parent)

    def _make_args(self, pages=1, batch_size=50):
        return make_args(pages=pages, batch_size=batch_size)

    def test_no_child_labels_returns_zero(self):
        client = ExtendedFakeGmailClient(labels=[make_user_label("Work", "W")])
        name_to_id = {"Work": "W"}
        with capture_stdout() as buf:
            result = self.sweep_one(client, name_to_id, "Work", self._make_args(), dry_run=False)
        self.assertEqual(result, 0)
        self.assertIn("No child labels", buf.getvalue())

    def test_dry_run_returns_message_count_without_modifying(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("Work", "W"),
            make_user_label("Work/Projects", "WP"),
        ])
        client.list_message_ids = MagicMock(return_value=["m1", "m2", "m3"])
        name_to_id = {"Work": "W", "Work/Projects": "WP"}
        with capture_stdout() as buf:
            result = self.sweep_one(client, name_to_id, "Work", self._make_args(), dry_run=True)
        self.assertEqual(result, 3)
        self.assertIn("Would add to 3 messages", buf.getvalue())
        self.assertEqual(client.modified_batches, [])

    def test_live_run_adds_parent_label_to_messages(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("Work", "W"),
            make_user_label("Work/Projects", "WP"),
        ])
        client.list_message_ids = MagicMock(return_value=["m1", "m2"])
        name_to_id = {"Work": "W", "Work/Projects": "WP"}
        with patch("mail.utils.batch.apply_in_chunks") as mock_apply, \
                capture_stdout() as buf:
            result = self.sweep_one(client, name_to_id, "Work", self._make_args(), dry_run=False)
        self.assertEqual(result, 2)
        mock_apply.assert_called_once()
        self.assertIn("Added to 2 messages", buf.getvalue())

    def test_creates_parent_label_when_missing_from_map(self):
        client = ExtendedFakeGmailClient(labels=[
            make_user_label("Work/Projects", "WP"),
        ])
        client.list_message_ids = MagicMock(return_value=["m1"])
        with patch("mail.utils.batch.apply_in_chunks"), capture_stdout():
            result = self.sweep_one(
                client, {"Work/Projects": "WP"},
                "Work", self._make_args(), dry_run=False,
            )
        self.assertEqual(result, 1)
        names = [lab["name"] for lab in client.labels]
        self.assertIn("Work", names)


# ---------------------------------------------------------------------------
# run_labels_sweep_parents (lines 409-423)
# ---------------------------------------------------------------------------


class TestRunLabelsSweepParents(unittest.TestCase):
    """Tests for run_labels_sweep_parents."""

    def _run_sweep_parents(self, labels, names, dry_run=False, pages=1, batch_size=50):
        client = ExtendedFakeGmailClient(labels=labels)
        args = make_args(names=names, dry_run=dry_run, pages=pages, batch_size=batch_size)
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client), \
                capture_stdout() as buf:
            from mail.labels.commands_doctor import run_labels_sweep_parents
            rc = run_labels_sweep_parents(args)
        return rc, buf.getvalue(), client

    def test_happy_path_returns_zero_and_reports_touched(self):
        labels = [
            make_user_label("Work", "W"),
            make_user_label("Work/Projects", "WP"),
        ]
        with patch("mail.labels.commands_doctor._sweep_one_parent", return_value=2):
            rc, out, _ = self._run_sweep_parents(labels, "Work")
        self.assertEqual(rc, 0)
        self.assertIn("Messages touched: 2", out)

    def test_empty_names_produces_zero_touched(self):
        rc, out, _ = self._run_sweep_parents([], "")
        self.assertEqual(rc, 0)
        self.assertIn("Messages touched: 0", out)

    def test_multiple_parents_accumulates_count(self):
        labels = [
            make_user_label("Work", "W"),
            make_user_label("Work/Projects", "WP"),
            make_user_label("Lists", "LS"),
            make_user_label("Lists/Newsletters", "LN"),
        ]
        with patch("mail.labels.commands_doctor._sweep_one_parent", return_value=3):
            rc, out, _ = self._run_sweep_parents(labels, "Work,Lists")
        self.assertEqual(rc, 0)
        self.assertIn("Messages touched: 6", out)


if __name__ == "__main__":
    unittest.main()
