"""Tests for apple_music.cli_helpers — format_timestamp, save_credential_value, _output_json."""

from __future__ import annotations

import configparser
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin


class TestFormatTimestamp(unittest.TestCase):
    """_format_timestamp renders unix timestamps as ISO-8601 UTC strings."""

    def test_none_returns_none(self) -> None:
        from apple_music.cli_helpers import _format_timestamp

        result = _format_timestamp(None)
        self.assertIsNone(result)

    def test_epoch_zero_renders_utc_string(self) -> None:
        from apple_music.cli_helpers import _format_timestamp

        result = _format_timestamp(0)
        self.assertIsNotNone(result)
        assert result is not None  # nosec B101 - type narrowing for mypy
        self.assertIsInstance(result, str)
        self.assertIn("1970-01-01", result)
        self.assertTrue(result.endswith("Z"), f"Expected Z suffix: {result}")

    def test_known_timestamp_renders_correctly(self) -> None:
        from apple_music.cli_helpers import _format_timestamp

        # 2024-01-15 12:00:00 UTC
        epoch = 1705320000
        result = _format_timestamp(epoch)
        self.assertIsNotNone(result)
        assert result is not None  # nosec B101 - type narrowing for mypy
        self.assertIn("2024-01-15", result)
        self.assertTrue(result.endswith("Z"))

    def test_output_is_iso8601_format(self) -> None:
        from apple_music.cli_helpers import _format_timestamp

        result = _format_timestamp(1705320000)
        assert result is not None  # nosec B101 - type narrowing for mypy
        # ISO-8601 format: YYYY-MM-DDTHH:MM:SS...Z
        self.assertIn("T", result)
        self.assertNotIn("+00:00", result)


class TestSaveCredentialValue(TempDirMixin, unittest.TestCase):
    """save_credential_value writes/updates credentials.ini atomically."""

    def _make_config(self, content: str = "") -> Path:
        path = Path(self.tmpdir) / "credentials.ini"
        path.write_text(content)
        return path

    def test_writes_new_key_to_existing_section(self) -> None:
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config("[musickit.personal]\ndeveloper_token = OLD\n")
        save_credential_value(config, "musickit.personal", "user_token", "NEWVAL")

        parser = configparser.ConfigParser()
        parser.read(config)
        self.assertEqual(parser.get("musickit.personal", "user_token"), "NEWVAL")

    def test_creates_section_when_missing(self) -> None:
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config("")
        save_credential_value(config, "musickit.personal", "developer_token", "DEVTOK")

        parser = configparser.ConfigParser()
        parser.read(config)
        self.assertTrue(parser.has_section("musickit.personal"))
        self.assertEqual(parser.get("musickit.personal", "developer_token"), "DEVTOK")

    def test_overwrites_existing_key(self) -> None:
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config("[musickit.personal]\ndeveloper_token = ORIGINAL\n")
        save_credential_value(config, "musickit.personal", "developer_token", "UPDATED")

        parser = configparser.ConfigParser()
        parser.read(config)
        self.assertEqual(parser.get("musickit.personal", "developer_token"), "UPDATED")

    def test_preserves_other_sections(self) -> None:
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config(
            "[musickit.personal]\nkey1 = val1\n"
            "[other.section]\nfoo = bar\n"
        )
        save_credential_value(config, "musickit.personal", "key2", "val2")

        parser = configparser.ConfigParser()
        parser.read(config)
        self.assertEqual(parser.get("other.section", "foo"), "bar")

    def test_preserves_existing_keys_in_section(self) -> None:
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config("[musickit.personal]\nexisting = preserved\n")
        save_credential_value(config, "musickit.personal", "new_key", "new_val")

        parser = configparser.ConfigParser()
        parser.read(config)
        self.assertEqual(parser.get("musickit.personal", "existing"), "preserved")
        self.assertEqual(parser.get("musickit.personal", "new_key"), "new_val")

    def test_cleans_up_temp_file_on_error(self) -> None:
        """Temp file must not be left behind when write fails."""
        from apple_music.cli_helpers import save_credential_value

        config = self._make_config("")
        tmpdir = Path(self.tmpdir)

        files_before = set(tmpdir.iterdir())
        with patch("apple_music.cli_helpers.os.fchmod", side_effect=OSError("permission denied")):
            with self.assertRaises(OSError):
                save_credential_value(config, "musickit.personal", "key", "val")

        files_after = set(tmpdir.iterdir())
        leaked = files_after - files_before
        self.assertEqual(
            leaked, set(), f"Leaked temp file(s): {leaked}"
        )


class TestOutputJson(unittest.TestCase):
    """_output_json writes JSON payload to stdout or a file path."""

    def test_writes_to_stdout_when_no_out(self) -> None:
        from apple_music.cli_helpers import _output_json

        args = MagicMock()
        args.pretty = False
        args.out = None
        payload = {"status": "ok", "count": 3}

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _output_json(args, payload)

        self.assertEqual(rc, 0)
        import json
        result = json.loads(buf.getvalue())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 3)

    def test_writes_to_file_when_out_given(self) -> None:
        from apple_music.cli_helpers import _output_json

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "result.json")
            args = MagicMock()
            args.pretty = False
            args.out = out_path
            payload = {"key": "value"}

            rc = _output_json(args, payload)
            self.assertEqual(rc, 0)

            import json
            data = json.loads(Path(out_path).read_text())
            self.assertEqual(data["key"], "value")

    def test_pretty_flag_produces_indented_json(self) -> None:
        from apple_music.cli_helpers import _output_json

        args = MagicMock()
        args.pretty = True
        args.out = None
        payload = {"a": 1}

        buf = io.StringIO()
        with redirect_stdout(buf):
            _output_json(args, payload)

        text = buf.getvalue()
        # Indented JSON has newlines between keys
        self.assertIn("\n", text)

    def test_returns_zero_exit_code(self) -> None:
        from apple_music.cli_helpers import _output_json

        args = MagicMock()
        args.pretty = False
        args.out = None

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _output_json(args, {})
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
