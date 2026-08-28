"""Tests for AccountsExportFiltersProcessor._process_safe (lines 117-140).

Covers:
- Happy path: iterating accounts, building provider, authenticating,
  mapping label ids to names, writing filters_<name>.yaml, returning ExportedFiltersInfo
- Empty account list: no exports produced
- Filter count reflects the number of DSL entries
- Label id -> name mapping applied to filter actions
- accounts_filter narrows which accounts are processed
- Error path: process() returns an error envelope when an exception is raised
"""
from __future__ import annotations

import os
import unittest
from dataclasses import dataclass, field
from typing import Dict, List
from unittest.mock import patch

from mail.accounts.pipeline_list_export import (
    AccountsExportFiltersProcessor,
    AccountsExportFiltersRequest,
)
from tests.fixtures import TempDirMixin


# ---------------------------------------------------------------------------
# Fake provider client
# ---------------------------------------------------------------------------


@dataclass
class FakeProviderClient:
    """Minimal fake provider client for export-filters tests."""

    labels: List[Dict] = field(default_factory=list)
    filters: List[Dict] = field(default_factory=list)
    authenticate_called: bool = field(default=False, init=False)

    def authenticate(self) -> None:
        self.authenticate_called = True

    def list_labels(self) -> List[Dict]:
        return list(self.labels)

    def list_filters(self, **_kwargs) -> List[Dict]:
        return list(self.filters)


def _make_label(label_id: str, name: str) -> Dict:
    return {"id": label_id, "name": name, "type": "user"}


def _make_filter(from_addr: str, label_ids: List[str]) -> Dict:
    return {
        "id": "F1",
        "criteria": {"from": from_addr},
        "action": {"addLabelIds": label_ids},
    }


def _make_account(name: str = "personal") -> Dict:
    return {"name": name, "provider": "gmail"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAccountsExportFiltersProcessor(TempDirMixin, unittest.TestCase):
    """Tests for AccountsExportFiltersProcessor._process_safe."""

    def _out_dir(self) -> str:
        out = os.path.join(self.tmpdir, "out")
        return out

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_happy_path_writes_yaml_file(self, mock_load, mock_build):
        """Single account produces a filters_<name>.yaml file."""
        client = FakeProviderClient(
            labels=[_make_label("LBL_1", "Newsletters")],
            filters=[_make_filter("news@example.com", ["LBL_1"])],
        )
        mock_load.return_value = [_make_account("personal")]
        mock_build.return_value = client

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        processor = AccountsExportFiltersProcessor()
        with patch("core.yamlio.dump_config"):
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(len(envelope.payload.exports), 1)
        exp = envelope.payload.exports[0]
        self.assertEqual(exp.account_name, "personal")
        self.assertIn("filters_personal.yaml", exp.output_path)
        self.assertEqual(exp.filter_count, 1)

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_authenticate_is_called(self, mock_load, mock_build):
        """authenticate() is called on the provider client."""
        client = FakeProviderClient(
            labels=[_make_label("LBL_1", "Work")],
            filters=[_make_filter("boss@corp.com", ["LBL_1"])],
        )
        mock_load.return_value = [_make_account("work")]
        mock_build.return_value = client

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            processor.process(request)

        self.assertTrue(client.authenticate_called)

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_label_id_to_name_mapping_applied(self, mock_load, mock_build):
        """Label IDs in filter actions are mapped to label names in the DSL."""
        client = FakeProviderClient(
            labels=[_make_label("LBL_NEWS", "Newsletters"), _make_label("LBL_ADS", "Ads")],
            filters=[_make_filter("news@example.com", ["LBL_NEWS", "LBL_ADS"])],
        )
        mock_load.return_value = [_make_account("personal")]
        mock_build.return_value = client

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        captured_docs = []

        def capture_dump(path, doc):
            captured_docs.append(doc)

        with patch("core.yamlio.dump_config", side_effect=capture_dump):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(len(captured_docs), 1)
        filters_dsl = captured_docs[0]["filters"]
        self.assertEqual(len(filters_dsl), 1)
        action = filters_dsl[0]["action"]
        self.assertIn("add", action)
        self.assertIn("Newsletters", action["add"])
        self.assertIn("Ads", action["add"])

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_empty_accounts_returns_empty_exports(self, mock_load, mock_build):
        """No accounts in config produces empty exports list."""
        mock_load.return_value = []

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(envelope.payload.exports, [])
        mock_build.assert_not_called()

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_filter_count_reflects_dsl_entries(self, mock_load, mock_build):
        """filter_count matches the number of filters returned by the provider."""
        client = FakeProviderClient(
            labels=[_make_label("LBL_A", "Alpha"), _make_label("LBL_B", "Beta")],
            filters=[
                _make_filter("a@example.com", ["LBL_A"]),
                _make_filter("b@example.com", ["LBL_B"]),
                _make_filter("c@example.com", []),
            ],
        )
        mock_load.return_value = [_make_account("personal")]
        mock_build.return_value = client

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(envelope.payload.exports[0].filter_count, 3)

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_multiple_accounts_each_get_separate_file(self, mock_load, mock_build):
        """Two accounts each produce a separate ExportedFiltersInfo."""
        client_a = FakeProviderClient(
            labels=[_make_label("LBL_A", "Alpha")],
            filters=[_make_filter("a@example.com", ["LBL_A"])],
        )
        client_b = FakeProviderClient(
            labels=[_make_label("LBL_B", "Beta")],
            filters=[],
        )
        mock_load.return_value = [_make_account("acct_a"), _make_account("acct_b")]
        mock_build.side_effect = [client_a, client_b]

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(len(envelope.payload.exports), 2)
        names = {e.account_name for e in envelope.payload.exports}
        self.assertIn("acct_a", names)
        self.assertIn("acct_b", names)

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_accounts_filter_narrows_processing(self, mock_load, mock_build):
        """accounts_filter (comma-separated string) restricts which accounts are iterated.

        Note: iter_accounts takes a comma-separated str | None. The field is typed
        list[str] | None in the dataclass but the processor passes it straight through.
        Pass a string to exercise the actual filter path.
        """
        client = FakeProviderClient(
            labels=[],
            filters=[],
        )
        mock_load.return_value = [_make_account("personal"), _make_account("work")]
        mock_build.return_value = client

        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=self._out_dir(),
            accounts_filter="personal",
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok(), envelope.diagnostics)
        self.assertEqual(len(envelope.payload.exports), 1)
        self.assertEqual(envelope.payload.exports[0].account_name, "personal")

    @patch("mail.accounts.helpers.load_accounts")
    def test_error_path_returns_error_envelope(self, mock_load):
        """An exception during processing returns an error envelope, not a raise."""
        mock_load.side_effect = FileNotFoundError("config not found")

        request = AccountsExportFiltersRequest(
            config_path="/missing/config.yaml",
            out_dir=self._out_dir(),
        )
        processor = AccountsExportFiltersProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("config not found", envelope.diagnostics.get("message", ""))

    @patch("mail.accounts.helpers.build_provider_for_account")
    @patch("mail.accounts.helpers.load_accounts")
    def test_output_path_in_export_info(self, mock_load, mock_build):
        """output_path in ExportedFiltersInfo points inside out_dir."""
        client = FakeProviderClient(labels=[], filters=[])
        mock_load.return_value = [_make_account("myaccount")]
        mock_build.return_value = client

        out = self._out_dir()
        request = AccountsExportFiltersRequest(
            config_path="/fake/config.yaml",
            out_dir=out,
        )
        with patch("core.yamlio.dump_config"):
            processor = AccountsExportFiltersProcessor()
            envelope = processor.process(request)

        exp = envelope.payload.exports[0]
        self.assertTrue(exp.output_path.startswith(out))
        self.assertIn("myaccount", exp.output_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
