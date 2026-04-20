"""Tests for core/secrets.py MaskingWriter and install_output_masking_from_env."""

from __future__ import annotations

import sys
import unittest
from io import StringIO

from core.secrets import MaskingWriter, install_output_masking_from_env


class TestMaskingWriterWrite(unittest.TestCase):
    def test_write_disabled_passes_through(self):
        buf = StringIO()
        writer = MaskingWriter(buf, enabled=False)
        writer.write("Bearer mytoken123\n")
        self.assertIn("Bearer mytoken123", buf.getvalue())

    def test_write_masks_sensitive_text(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.write("Authorization: Bearer secret-token\n")
        self.assertIn("***REDACTED***", buf.getvalue())
        self.assertNotIn("secret-token", buf.getvalue())

    def test_write_passes_through_normal_text(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.write("Normal log message\n")
        self.assertIn("Normal log message", buf.getvalue())

    def test_write_buffers_incomplete_lines(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        # Write text without newline - should be buffered
        writer.write("partial")
        # Not yet flushed to buffer
        writer.flush()
        self.assertIn("partial", buf.getvalue())

    def test_write_processes_complete_lines(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.write("line1\nline2\n")
        self.assertIn("line1", buf.getvalue())
        self.assertIn("line2", buf.getvalue())

    def test_write_returns_written_count(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        result = writer.write("hello\n")
        self.assertIsInstance(result, int)

    def test_writelines(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.writelines(["line1\n", "line2\n"])
        self.assertIn("line1", buf.getvalue())
        self.assertIn("line2", buf.getvalue())


class TestMaskingWriterFlush(unittest.TestCase):
    def test_flush_writes_buffered_content(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.write("no newline")
        writer.flush()
        self.assertIn("no newline", buf.getvalue())

    def test_flush_clears_buffer(self):
        buf = StringIO()
        writer = MaskingWriter(buf)
        writer.write("buffered")
        writer.flush()
        # After flush, buffer should be empty
        self.assertEqual(writer._buffer, "")

    def test_flush_disabled_still_flushes_stream(self):
        buf = StringIO()
        writer = MaskingWriter(buf, enabled=False)
        writer.flush()  # Should not raise

    def test_flush_handles_broken_pipe(self):
        buf = unittest.mock.MagicMock()
        buf.write.side_effect = BrokenPipeError()
        writer = MaskingWriter(buf)
        writer._buffer = "some text"
        # Should not raise BrokenPipeError
        writer.flush()

    def test_flush_handles_stream_flush_broken_pipe(self):
        buf = unittest.mock.MagicMock()
        buf.write.return_value = 5
        buf.flush.side_effect = BrokenPipeError()
        writer = MaskingWriter(buf)
        # Should not raise
        writer.flush()


class TestMaskingWriterIsatty(unittest.TestCase):
    def test_isatty_delegates_to_stream(self):
        buf = unittest.mock.MagicMock()
        buf.isatty.return_value = True
        writer = MaskingWriter(buf)
        self.assertTrue(writer.isatty())

    def test_isatty_returns_false_on_exception(self):
        buf = unittest.mock.MagicMock()
        buf.isatty.side_effect = AttributeError("no isatty")
        writer = MaskingWriter(buf)
        self.assertFalse(writer.isatty())


class TestMaskingWriterEncoding(unittest.TestCase):
    def test_encoding_delegates_to_stream(self):
        buf = unittest.mock.MagicMock()
        buf.encoding = "utf-8"
        writer = MaskingWriter(buf)
        self.assertEqual(writer.encoding, "utf-8")

    def test_encoding_none_when_not_present(self):
        buf = unittest.mock.MagicMock(spec=[])
        writer = MaskingWriter(buf)
        self.assertIsNone(writer.encoding)


class TestMaskingWriterGetattr(unittest.TestCase):
    def test_getattr_delegates_to_stream(self):
        buf = unittest.mock.MagicMock()
        buf.name = "/dev/stdout"
        writer = MaskingWriter(buf)
        self.assertEqual(writer.name, "/dev/stdout")


class TestInstallOutputMasking(unittest.TestCase):
    def test_install_when_enabled(self):
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_OUTPUTS": "1", "SRE_MASK_BYPASS": ""}):
                install_output_masking_from_env()
            self.assertIsInstance(sys.stdout, MaskingWriter)
            self.assertIsInstance(sys.stderr, MaskingWriter)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_install_skipped_when_bypass_set(self):
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_BYPASS": "1"}):
                install_output_masking_from_env()
            # Should not be wrapped
            self.assertNotIsInstance(sys.stdout, MaskingWriter)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_install_skipped_when_disabled(self):
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_OUTPUTS": "0", "SRE_MASK_BYPASS": ""}):
                install_output_masking_from_env()
            self.assertNotIsInstance(sys.stdout, MaskingWriter)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_install_skipped_when_false(self):
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_OUTPUTS": "false", "SRE_MASK_BYPASS": ""}):
                install_output_masking_from_env()
            self.assertNotIsInstance(sys.stdout, MaskingWriter)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_install_idempotent(self):
        """Installing twice should not double-wrap."""
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_OUTPUTS": "1", "SRE_MASK_BYPASS": ""}):
                install_output_masking_from_env()
                install_output_masking_from_env()
            # The outer stream is MaskingWriter but not double-wrapped
            self.assertIsInstance(sys.stdout, MaskingWriter)
            # The inner stream should NOT be a MaskingWriter
            self.assertNotIsInstance(sys.stdout._stream, MaskingWriter)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_bypass_with_no_value(self):
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            with unittest.mock.patch.dict("os.environ", {"SRE_MASK_BYPASS": "no"}):
                # "no" is in the bypass-disable set, so should install
                install_output_masking_from_env()
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

    def test_handles_exception_gracefully(self):
        # Should not propagate any exceptions
        with unittest.mock.patch("sys.stdout", side_effect=Exception("boom")):
            install_output_masking_from_env()  # Should not raise


if __name__ == "__main__":
    unittest.main()
