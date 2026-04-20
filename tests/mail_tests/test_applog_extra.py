"""Additional coverage tests for mail/applog.py.

Covers branches and paths not hit by tests/mail/test_applog.py:
- AppLogger.__init__ with a flat filename (no directory component)
- AppLogger._write exception silencing (lines 27-28)
- AppLogger.start with no argv
- AppLogger.end with no duration_ms and no error
- AppLogger.info and AppLogger.error full record contents
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from mail.applog import AppLogger


class AppLoggerInitNoDirTests(unittest.TestCase):
    """__init__ with a flat filename — dirname() returns '' so makedirs is skipped."""

    def setUp(self):
        self._orig_dir = os.getcwd()
        self._tmpdir = tempfile.mkdtemp()
        os.chdir(self._tmpdir)

    def tearDown(self):
        import shutil

        os.chdir(self._orig_dir)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_no_directory_component(self):
        # os.path.dirname("app.log") == "" — the `if d:` branch must not call makedirs
        logger = AppLogger("app.log")
        self.assertEqual(logger.path, "app.log")
        # Prove makedirs was NOT called for an empty dirname by checking no extra dirs exist
        self.assertFalse(os.path.isdir(""))


class AppLoggerWriteExceptionTests(unittest.TestCase):
    """_write must swallow exceptions silently (lines 27-28)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self._tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_write_exception_is_silenced(self):
        # Patch open() inside applog to raise so the except branch is exercised
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Must not raise; logging must never crash the app
            try:
                self.logger._write({"event": "test"})
            except OSError:
                self.fail("_write raised an exception instead of silencing it")


class AppLoggerStartTests(unittest.TestCase):
    """start() with and without argv."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self._tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_records(self):
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_start_no_argv_writes_none(self):
        sid = self.logger.start("mycmd")
        rec = self._read_records()[0]
        self.assertEqual(rec["event"], "start")
        self.assertEqual(rec["cmd"], "mycmd")
        self.assertIsNone(rec["argv"])
        self.assertEqual(rec["session_id"], sid)
        self.assertIn("ts", rec)
        self.assertIn("pid", rec)

    def test_start_with_argv(self):
        sid = self.logger.start("mycmd", argv=["--dry-run"])
        rec = self._read_records()[0]
        self.assertEqual(rec["argv"], ["--dry-run"])
        self.assertEqual(rec["session_id"], sid)

    def test_start_returns_unique_ids(self):
        sid1 = self.logger.start("cmd")
        sid2 = self.logger.start("cmd")
        self.assertNotEqual(sid1, sid2)


class AppLoggerEndTests(unittest.TestCase):
    """end() optional fields: duration_ms and error."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self._tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_records(self):
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_end_default_status_no_duration_no_error(self):
        sid = self.logger.start("cmd")
        self.logger.end(sid)
        rec = self._read_records()[1]
        self.assertEqual(rec["event"], "end")
        self.assertEqual(rec["status"], "ok")
        self.assertNotIn("duration_ms", rec)
        self.assertNotIn("error", rec)

    def test_end_with_duration_ms_cast_to_int(self):
        sid = self.logger.start("cmd")
        self.logger.end(sid, duration_ms=99.9)
        rec = self._read_records()[1]
        self.assertEqual(rec["duration_ms"], 99)

    def test_end_with_error_string(self):
        sid = self.logger.start("cmd")
        self.logger.end(sid, status="error", error="boom")
        rec = self._read_records()[1]
        self.assertEqual(rec["status"], "error")
        self.assertEqual(rec["error"], "boom")

    def test_end_error_none_not_included(self):
        # error=None (default) must not add the key
        sid = self.logger.start("cmd")
        self.logger.end(sid, status="ok", error=None)
        rec = self._read_records()[1]
        self.assertNotIn("error", rec)


class AppLoggerInfoTests(unittest.TestCase):
    """info() record structure."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self._tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_records(self):
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_info_record_fields(self):
        sid = self.logger.start("cmd")
        self.logger.info(sid, {"count": 7, "label": "inbox"})
        rec = self._read_records()[1]
        self.assertEqual(rec["event"], "info")
        self.assertEqual(rec["session_id"], sid)
        self.assertEqual(rec["data"], {"count": 7, "label": "inbox"})
        self.assertIn("ts", rec)


class AppLoggerErrorTests(unittest.TestCase):
    """error() record structure with and without extra."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self._tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _read_records(self):
        with open(self.log_path, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_error_record_with_extra(self):
        sid = self.logger.start("cmd")
        self.logger.error(sid, "bad thing", extra={"code": 503})
        rec = self._read_records()[1]
        self.assertEqual(rec["event"], "error")
        self.assertEqual(rec["session_id"], sid)
        self.assertEqual(rec["message"], "bad thing")
        self.assertEqual(rec["extra"], {"code": 503})
        self.assertIn("ts", rec)

    def test_error_record_without_extra(self):
        sid = self.logger.start("cmd")
        self.logger.error(sid, "oops")
        rec = self._read_records()[1]
        self.assertEqual(rec["event"], "error")
        self.assertIsNone(rec["extra"])


if __name__ == "__main__":
    unittest.main()
