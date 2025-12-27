import os
import tempfile
import types
import unittest
from types import SimpleNamespace

from tests.fixtures import capture_stdout, FakeGmailClient


def stub_gmail_provider(fake):
    mod = types.ModuleType('mail.utils.cli_helpers')

    def gmail_provider_from_args(args):
        return fake
    mod.gmail_provider_from_args = gmail_provider_from_args  # type: ignore
    return mod


class TestGmailScanFlows(unittest.TestCase):
    def test_scan_receipts_extracts_event(self):
        import sys
        text = "\n".join([
            "Enrollment in Swim Kids 5 (RH)",
            "Meeting Dates: From January 1, 2025 to March 1, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Elgin West Community Centre",
        ])
        fake = FakeGmailClient(
            message_ids_by_query={"richmondhill": ["m1"]},
            messages={"m1": {"text": text}}
        )
        old_mod = sys.modules.get('mail.utils.cli_helpers')
        sys.modules['mail.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendars.gmail.commands import run_gmail_scan_receipts
        try:
            tf = tempfile.NamedTemporaryFile('w+', delete=False, suffix='.yaml')
            tf.close()
            args = SimpleNamespace(from_text='richmondhill.ca', days=365, pages=1, page_size=10, query=None, out=tf.name,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None)
            with capture_stdout() as buf:
                rc = run_gmail_scan_receipts(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('wrote 1 events to', out)
            os.unlink(tf.name)
        finally:
            if old_mod is None:
                sys.modules.pop('mail.utils.cli_helpers', None)
            else:
                sys.modules['mail.utils.cli_helpers'] = old_mod

    def test_scan_classes_extracts_schedule_lines(self):
        import sys
        body = "\n".join([
            "Subject: Schedule",
            "Monday 5:00 pm to 5:30 pm",
            "Wednesday 6:00 pm to 6:30 pm"
        ])
        fake = FakeGmailClient(
            message_ids_by_query={"active": ["m1"]},
            messages={"m1": {"text": body}}
        )
        old_mod = sys.modules.get('mail.utils.cli_helpers')
        sys.modules['mail.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendars.gmail.commands import run_gmail_scan_classes
        try:
            args = SimpleNamespace(from_text='active rh', days=60, pages=1, page_size=10, query=None, inbox_only=False, out=None,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None)
            with capture_stdout() as buf:
                rc = run_gmail_scan_classes(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('candidate recurring', out)
        finally:
            if old_mod is None:
                sys.modules.pop('mail.utils.cli_helpers', None)
            else:
                sys.modules['mail.utils.cli_helpers'] = old_mod

    def test_scan_activerh_builds_query_delegates(self):
        import sys
        text = "\n".join([
            "Enrollment in Swim Kids 2",
            "Meeting Dates: From January 5, 2025 to March 5, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Bayview Hill Community Centre",
        ])
        # Use empty key to match any query (activerh builds a custom query)
        fake = FakeGmailClient(
            message_ids_by_query={"": ["m1"]},
            messages={"m1": {"text": text}}
        )
        old_mod = sys.modules.get('mail.utils.cli_helpers')
        sys.modules['mail.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendars.gmail.commands import run_gmail_scan_activerh
        try:
            tf = tempfile.NamedTemporaryFile('w+', delete=False, suffix='.yaml')
            tf.close()
            args = SimpleNamespace(days=365, pages=1, page_size=10, query=None, out=tf.name,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None, from_text=None)
            with capture_stdout() as buf:
                rc = run_gmail_scan_activerh(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('wrote 1 events to', out)
            os.unlink(tf.name)
        finally:
            if old_mod is None:
                sys.modules.pop('mail.utils.cli_helpers', None)
            else:
                sys.modules['mail.utils.cli_helpers'] = old_mod


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
