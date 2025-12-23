import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeProvider:
    def __init__(self, ids_text_map):
        self.ids = list(ids_text_map.keys())
        self.map = ids_text_map
        self.authed = False

    def authenticate(self):
        self.authed = True

    def list_message_ids(self, query, max_pages=1, page_size=10):
        return self.ids

    def get_message_text(self, mid):
        return self.map.get(mid, "")


def stub_gmail_provider(fake):
    mod = types.ModuleType('mail_assistant.utils.cli_helpers')
    def gmail_provider_from_args(args):
        return fake
    mod.gmail_provider_from_args = gmail_provider_from_args  # type: ignore
    return mod


class TestGmailScanFlows(unittest.TestCase):
    def test_scan_receipts_extracts_event(self):
        import sys
        text = (
            "Enrollment in Swim Kids 5 (RH)",
            "Meeting Dates: From January 1, 2025 to March 1, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Elgin West Community Centre",
        )
        fake = FakeProvider({"m1": "\n".join(text)})
        old_mod = sys.modules.get('mail_assistant.utils.cli_helpers')
        sys.modules['mail_assistant.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendar_assistant.gmail.commands import run_gmail_scan_receipts
        import tempfile
        import os
        try:
            tf = tempfile.NamedTemporaryFile('w+', delete=False, suffix='.yaml')
            tf.close()
            args = SimpleNamespace(from_text='richmondhill.ca', days=365, pages=1, page_size=10, query=None, out=tf.name,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_gmail_scan_receipts(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('wrote 1 events to', out)
            os.unlink(tf.name)
        finally:
            if old_mod is None:
                sys.modules.pop('mail_assistant.utils.cli_helpers', None)
            else:
                sys.modules['mail_assistant.utils.cli_helpers'] = old_mod

    def test_scan_classes_extracts_schedule_lines(self):
        import sys
        body = (
            "Subject: Schedule", 
            "Monday 5:00 pm to 5:30 pm", 
            "Wednesday 6:00 pm to 6:30 pm"
        )
        fake = FakeProvider({"m1": "\n".join(body)})
        old_mod = sys.modules.get('mail_assistant.utils.cli_helpers')
        sys.modules['mail_assistant.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendar_assistant.gmail.commands import run_gmail_scan_classes
        try:
            args = SimpleNamespace(from_text='active rh', days=60, pages=1, page_size=10, query=None, inbox_only=False, out=None,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_gmail_scan_classes(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('candidate recurring', out)
        finally:
            if old_mod is None:
                sys.modules.pop('mail_assistant.utils.cli_helpers', None)
            else:
                sys.modules['mail_assistant.utils.cli_helpers'] = old_mod

    def test_scan_activerh_builds_query_delegates(self):
        import sys
        import tempfile
        import os
        text = (
            "Enrollment in Swim Kids 2",
            "Meeting Dates: From January 5, 2025 to March 5, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Bayview Hill Community Centre",
        )
        fake = FakeProvider({"m1": "\n".join(text)})
        old_mod = sys.modules.get('mail_assistant.utils.cli_helpers')
        sys.modules['mail_assistant.utils.cli_helpers'] = stub_gmail_provider(fake)
        from calendar_assistant.gmail.commands import run_gmail_scan_activerh
        try:
            tf = tempfile.NamedTemporaryFile('w+', delete=False, suffix='.yaml')
            tf.close()
            args = SimpleNamespace(days=365, pages=1, page_size=10, query=None, out=tf.name,
                                   profile=None, credentials=None, token=None, cache=None, calendar=None, from_text=None)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_gmail_scan_activerh(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('wrote 1 events to', out)
            os.unlink(tf.name)
        finally:
            if old_mod is None:
                sys.modules.pop('mail_assistant.utils.cli_helpers', None)
            else:
                sys.modules['mail_assistant.utils.cli_helpers'] = old_mod


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
