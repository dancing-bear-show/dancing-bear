import io
import unittest
from pathlib import Path
from contextlib import redirect_stdout


class TestScheduleCompress(unittest.TestCase):

    def test_compress_infers_weekly_series_with_exdates(self):
        import tempfile
        import textwrap
        from schedule import __main__ as sa
        plan = textwrap.dedent(
            """
            events:
              - subject: Leisure Swim
                start: 2025-10-06T18:00:00
                end: 2025-10-06T19:00:00
                location: Pool
              - subject: Leisure Swim
                start: 2025-10-20T18:00:00
                end: 2025-10-20T19:00:00
                location: Pool
              - subject: Public Skating
                start: 2025-10-10T18:00:00
                end: 2025-10-10T19:00:00
                location: Rink
            """
        ).strip()
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.yaml"; inp.write_text(plan, encoding="utf-8")
            outp = Path(td) / "out.yaml"
            args = type("Args", (), {"in_path": str(inp), "out": str(outp), "calendar": "Activities", "min_occur": 2})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = sa._cmd_compress(args)
            self.assertEqual(rc, 0)
            out = outp.read_text(encoding="utf-8")
            self.assertIn("repeat: weekly", out)
            self.assertIn("byday:", out)
            self.assertIn("- MO", out)
            self.assertIn("start_time: '18:00'", out)
            self.assertIn("end_time: '19:00'", out)
            # Expect exdate for missing 2025-10-13
            self.assertIn("exdates:", out)
            self.assertIn("2025-10-13", out)
            # One-off preserved
            self.assertIn("Public Skating", out)


if __name__ == "__main__":
    unittest.main()

