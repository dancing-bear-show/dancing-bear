import io
import unittest
from types import SimpleNamespace
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch


class TestScheduleVerifySync(unittest.TestCase):

    def _write_plan(self, tmpdir: Path, yaml_text: str) -> Path:
        p = tmpdir / "plan.yaml"
        p.write_text(yaml_text, encoding="utf-8")
        return p

    def test_verify_subject_time_with_exdates(self):
        # Plan: weekly Monday 18:00–19:00 from 2025-10-06 to 2025-10-20 with exdate 2025-10-13
        import tempfile
        import textwrap
        from schedule.cli import main as sa

        with tempfile.TemporaryDirectory() as td:
            plan = self._write_plan(Path(td), textwrap.dedent(
                """
                events:
                  - subject: Leisure Swim
                    repeat: weekly
                    byday: [MO]
                    start_time: "18:00"
                    end_time: "19:00"
                    range: { start_date: 2025-10-06, until: 2025-10-20 }
                    exdates: [2025-10-13]
                """
            ).strip())

            # Outlook returns occurrences on 10/06 and 10/20 (10/13 excluded)
            occ = [
                {"subject": "Leisure Swim", "start": {"dateTime": "2025-10-06T18:00:00"}, "end": {"dateTime": "2025-10-06T19:00:00"}},
                {"subject": "Leisure Swim", "start": {"dateTime": "2025-10-20T18:00:00"}, "end": {"dateTime": "2025-10-20T19:00:00"}},
            ]

            class FakeOutlook:
                def __init__(self, *a, **k):
                    pass
                def authenticate(self):
                    return None
                def list_events_in_range(self, **kwargs):
                    return occ

            args = SimpleNamespace(plan=str(plan), calendar="Activities", from_date="2025-10-01", to_date="2025-10-31", match="subject-time", profile=None, client_id="dummy", tenant="consumers", token=None)
            buf = io.StringIO()
            with patch("mail.outlook_api.OutlookClient", new=FakeOutlook), redirect_stdout(buf):
                rc = sa._cmd_verify(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Missing: none", out)

    def test_verify_subject_time_reports_missing(self):
        import tempfile
        import textwrap
        from schedule.cli import main as sa
        with tempfile.TemporaryDirectory() as td:
            plan = self._write_plan(Path(td), textwrap.dedent(
                """
                events:
                  - subject: Chess
                    repeat: weekly
                    byday: [SU]
                    start_time: "10:00"
                    end_time: "11:00"
                    range: { start_date: 2025-10-05, until: 2025-10-19 }
                """
            ).strip())
            # Outlook only has 10/05; missing 10/12 and 10/19
            occ = [
                {"subject": "Chess", "start": {"dateTime": "2025-10-05T10:00:00"}, "end": {"dateTime": "2025-10-05T11:00:00"}},
            ]

            class FakeOutlook:
                def __init__(self, *a, **k):
                    pass
                def authenticate(self):
                    return None
                def list_events_in_range(self, **kwargs):
                    return occ

            args = SimpleNamespace(plan=str(plan), calendar="Your Family", from_date="2025-10-01", to_date="2025-10-31", match="subject-time", profile=None, client_id="dummy", tenant="consumers", token=None)
            buf = io.StringIO()
            with patch("mail.outlook_api.OutlookClient", new=FakeOutlook), redirect_stdout(buf):
                rc = sa._cmd_verify(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Missing (subject@time):", out)

    def test_sync_dry_run_counts_subject_time(self):
        import tempfile
        import textwrap
        from schedule.cli import main as sa
        with tempfile.TemporaryDirectory() as td:
            plan = self._write_plan(Path(td), textwrap.dedent(
                """
                events:
                  - subject: Leisure Swim
                    repeat: weekly
                    byday: [SU]
                    start_time: "10:00"
                    end_time: "11:00"
                    range: { start_date: 2025-10-01, until: 2025-10-31 }
                  - subject: Public Skating
                    start: 2025-10-10T18:00:00
                    end: 2025-10-10T19:00:00
                """
            ).strip())

            # Outlook occurrences: Leisure Swim only on 10/05; extra wrong one-off on 10/06
            occ = [
                {"subject": "Leisure Swim", "start": {"dateTime": "2025-10-05T10:00:00"}, "end": {"dateTime": "2025-10-05T11:00:00"}, "type": "occurrence", "seriesMasterId": "SID1", "id": "OCC1"},
                {"subject": "Leisure Swim", "start": {"dateTime": "2025-10-06T10:00:00"}, "end": {"dateTime": "2025-10-06T11:00:00"}, "type": "singleInstance", "id": "OID1"},
            ]

            class FakeOutlook:
                def __init__(self, *a, **k):
                    pass
                def authenticate(self):
                    return None
                def ensure_calendar(self, name: str) -> str:
                    return "CAL123"
                def list_events_in_range(self, **kwargs):
                    return occ

            args = SimpleNamespace(plan=str(plan), calendar="Activities", from_date="2025-10-01", to_date="2025-10-31", match="subject-time", delete_missing=True, apply=False, profile=None, client_id="dummy", tenant="consumers", token=None)
            buf = io.StringIO()
            with patch("mail.outlook_api.OutlookClient", new=FakeOutlook), redirect_stdout(buf):
                rc = sa._cmd_sync(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Would create series: 0", out)
            self.assertIn("Would create one-offs: 1", out)
            self.assertIn("Would delete extraneous occurrences: 1 (match=subject-time)", out)

    def test_export_writes_yaml(self):
        import tempfile
        from schedule.cli import main as sa
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "activities.yaml"
            evs = [
                {"subject": "Leisure Swim", "start": {"dateTime": "2025-10-05T10:00:00"}, "end": {"dateTime": "2025-10-05T11:00:00"}, "location": {"displayName": "Pool"}},
                {"subject": "Public Skating", "start": {"dateTime": "2025-10-06T10:00:00"}, "end": {"dateTime": "2025-10-06T11:00:00"}, "location": {"displayName": "Rink"}},
            ]

            class FakeOutlook:
                def __init__(self, *a, **k):
                    pass
                def authenticate(self):
                    return None
                def list_events_in_range(self, **kwargs):
                    return evs

            args = SimpleNamespace(calendar="Activities", from_date="2025-10-01", to_date="2025-10-31", out=str(out), profile=None, client_id="dummy", tenant="consumers", token=None)
            buf = io.StringIO()
            with patch("mail.outlook_api.OutlookClient", new=FakeOutlook), redirect_stdout(buf):
                rc = sa._cmd_export(args)
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            txt = out.read_text(encoding="utf-8")
            self.assertIn("events:", txt)
            self.assertIn("Leisure Swim", txt)


if __name__ == "__main__":
    unittest.main()
