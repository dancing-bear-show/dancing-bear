"""Tests for calendars/cli/gmail.py registration helper."""

import argparse
import unittest


class TestGmailCliRegister(unittest.TestCase):
    """Test the Gmail calendar CLI registration helper."""

    def _make_mock_func(self, name):
        """Create a mock function for testing."""
        def mock_func(args):
            return name
        return mock_func

    def _make_mock_add_auth_args(self):
        """Create a mock add_common_gmail_auth_args function."""
        def add_auth_args(parser):
            parser.add_argument("--credentials", help="Path to credentials")
            parser.add_argument("--token", help="Path to token")
        return add_auth_args

    def _make_mock_add_paging_args(self):
        """Create a mock add_common_gmail_paging_args function."""
        def add_paging_args(parser, default_days=7, default_pages=1, default_page_size=10):
            parser.add_argument("--days", type=int, default=default_days)
            parser.add_argument("--pages", type=int, default=default_pages)
            parser.add_argument("--page-size", type=int, default=default_page_size)
        return add_paging_args

    def test_register_creates_gmail_parser(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        p_gmail = register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        self.assertIsNotNone(p_gmail)

    def test_register_adds_scan_classes_subcommand(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "scan-classes", "--out", "test.yaml"])
        self.assertEqual(args.command, "gmail")
        self.assertEqual(args.gmail_cmd, "scan-classes")
        self.assertEqual(args.out, "test.yaml")

    def test_register_adds_scan_receipts_subcommand(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "scan-receipts", "--out", "receipts.yaml"])
        self.assertEqual(args.gmail_cmd, "scan-receipts")
        self.assertEqual(args.out, "receipts.yaml")

    def test_register_adds_scan_activerh_subcommand(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "scan-activerh", "--out", "activerh.yaml"])
        self.assertEqual(args.gmail_cmd, "scan-activerh")
        self.assertEqual(args.out, "activerh.yaml")

    def test_register_adds_mail_list_subcommand(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "mail-list", "--inbox-only"])
        self.assertEqual(args.gmail_cmd, "mail-list")
        self.assertTrue(args.inbox_only)

    def test_register_adds_sweep_top_subcommand(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "sweep-top", "--top", "20"])
        self.assertEqual(args.gmail_cmd, "sweep-top")
        self.assertEqual(args.top, 20)

    def test_scan_classes_has_from_text_default(self):
        from calendars.cli.gmail import register

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register(
            subparsers,
            f_scan_classes=self._make_mock_func("scan_classes"),
            f_scan_receipts=self._make_mock_func("scan_receipts"),
            f_scan_activerh=self._make_mock_func("scan_activerh"),
            f_mail_list=self._make_mock_func("mail_list"),
            f_sweep_top=self._make_mock_func("sweep_top"),
            add_common_gmail_auth_args=self._make_mock_add_auth_args(),
            add_common_gmail_paging_args=self._make_mock_add_paging_args(),
        )

        args = parser.parse_args(["gmail", "scan-classes"])
        self.assertEqual(args.from_text, "active rh")


if __name__ == "__main__":
    unittest.main(verbosity=2)
