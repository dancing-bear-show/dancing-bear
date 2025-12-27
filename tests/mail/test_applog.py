"""Tests for mail/applog.py JSON structured logging."""

import json
import os
import unittest

from tests.fixtures import TempDirMixin

from mail.applog import AppLogger


class AppLoggerTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.log_path = os.path.join(self.tmpdir, "app.log")
        self.logger = AppLogger(self.log_path)

    def _read_records(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_init_creates_directory(self):
        nested_path = os.path.join(self.tmpdir, "nested", "dir", "app.log")
        AppLogger(nested_path)
        self.assertTrue(os.path.isdir(os.path.dirname(nested_path)))

    def test_start_returns_session_id(self):
        session_id = self.logger.start("test-cmd")
        self.assertIsInstance(session_id, str)
        self.assertGreater(len(session_id), 0)

    def test_start_writes_record(self):
        session_id = self.logger.start("test-cmd", argv=["--flag", "value"])
        records = self._read_records()

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["event"], "start")
        self.assertEqual(rec["cmd"], "test-cmd")
        self.assertEqual(rec["argv"], ["--flag", "value"])
        self.assertEqual(rec["session_id"], session_id)
        self.assertIn("ts", rec)
        self.assertIn("pid", rec)

    def test_end_writes_record(self):
        session_id = self.logger.start("test-cmd")
        self.logger.end(session_id, status="ok", duration_ms=123)

        records = self._read_records()
        self.assertEqual(len(records), 2)
        end_rec = records[1]
        self.assertEqual(end_rec["event"], "end")
        self.assertEqual(end_rec["session_id"], session_id)
        self.assertEqual(end_rec["status"], "ok")
        self.assertEqual(end_rec["duration_ms"], 123)

    def test_end_with_error(self):
        session_id = self.logger.start("test-cmd")
        self.logger.end(session_id, status="error", error="Something failed")

        records = self._read_records()
        end_rec = records[1]
        self.assertEqual(end_rec["status"], "error")
        self.assertEqual(end_rec["error"], "Something failed")

    def test_info_writes_record(self):
        session_id = self.logger.start("test-cmd")
        self.logger.info(session_id, {"key": "value", "count": 42})

        records = self._read_records()
        self.assertEqual(len(records), 2)
        info_rec = records[1]
        self.assertEqual(info_rec["event"], "info")
        self.assertEqual(info_rec["session_id"], session_id)
        self.assertEqual(info_rec["data"], {"key": "value", "count": 42})

    def test_error_writes_record(self):
        session_id = self.logger.start("test-cmd")
        self.logger.error(session_id, "Error message", extra={"code": 500})

        records = self._read_records()
        error_rec = records[1]
        self.assertEqual(error_rec["event"], "error")
        self.assertEqual(error_rec["message"], "Error message")
        self.assertEqual(error_rec["extra"], {"code": 500})

    def test_error_without_extra(self):
        session_id = self.logger.start("test-cmd")
        self.logger.error(session_id, "Error message")

        records = self._read_records()
        error_rec = records[1]
        self.assertEqual(error_rec["extra"], None)

    def test_multiple_sessions(self):
        sid1 = self.logger.start("cmd1")
        sid2 = self.logger.start("cmd2")

        self.assertNotEqual(sid1, sid2)

        records = self._read_records()
        self.assertEqual(len(records), 2)

    def test_unicode_content(self):
        session_id = self.logger.start("test-cmd")
        self.logger.info(session_id, {"message": "Test émojis 🎉"})

        records = self._read_records()
        self.assertEqual(records[1]["data"]["message"], "Test émojis 🎉")

    def test_timestamp_is_numeric(self):
        session_id = self.logger.start("test-cmd")
        records = self._read_records()
        self.assertIsInstance(records[0]["ts"], float)

    def test_append_mode(self):
        # First write
        self.logger.start("cmd1")
        # Second logger instance appends
        logger2 = AppLogger(self.log_path)
        logger2.start("cmd2")

        records = self._read_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["cmd"], "cmd1")
        self.assertEqual(records[1]["cmd"], "cmd2")

    def test_duration_ms_converted_to_int(self):
        session_id = self.logger.start("test-cmd")
        self.logger.end(session_id, duration_ms=123.7)

        records = self._read_records()
        self.assertEqual(records[1]["duration_ms"], 123)


if __name__ == "__main__":
    unittest.main()
