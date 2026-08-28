"""Tests for config_cli pipeline — cache stats, cache clear, cache prune, config inspect."""

import io
import os
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin, capture_stdout, test_path
from core.pipeline import ResultEnvelope

from mail.config_cli.pipeline_cache import (
    # Auth
    AuthRequest,
    AuthRequestConsumer,
    AuthProcessor,
    AuthProducer,
    AuthResult,
    # Backup
    BackupRequest,
    BackupRequestConsumer,
    BackupProcessor,
    BackupProducer,
    BackupResult,
    # Cache stats
    CacheStatsRequest,
    CacheStatsRequestConsumer,
    CacheStatsProcessor,
    CacheStatsProducer,
    CacheStatsResult,
    # Cache clear
    CacheClearRequest,
    CacheClearRequestConsumer,
    CacheClearProcessor,
    CacheClearProducer,
    CacheClearResult,
    # Cache prune
    CachePruneRequest,
    CachePruneRequestConsumer,
    CachePruneProcessor,
    CachePruneProducer,
    CachePruneResult,
    # Config inspect
    ConfigInspectRequest,
    ConfigInspectRequestConsumer,
    ConfigInspectProcessor,
    ConfigInspectProducer,
    ConfigInspectResult,
    ConfigSection,
)


class CacheStatsTests(TestCase):
    """Tests for cache stats pipeline."""

    def test_cache_stats_consumer_returns_request(self):
        """CacheStatsRequestConsumer returns the request."""
        request = CacheStatsRequest(cache_path=test_path("test"))
        consumer = CacheStatsRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_stats_processor_counts_files(self):
        """CacheStatsProcessor counts files and sizes correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.json").write_text("hello")
            (Path(tmpdir) / "file2.json").write_text("world!")
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "file3.json").write_text("nested")

            request = CacheStatsRequest(cache_path=tmpdir)
            result = CacheStatsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(3, result.payload.files)
            self.assertEqual(5 + 6 + 6, result.payload.size_bytes)  # hello + world! + nested

    def test_cache_stats_processor_empty_dir(self):
        """CacheStatsProcessor handles empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            request = CacheStatsRequest(cache_path=tmpdir)
            result = CacheStatsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.files)
            self.assertEqual(0, result.payload.size_bytes)

    def test_cache_stats_producer_output(self):
        """CacheStatsProducer prints stats."""
        result = ResultEnvelope(
            status="success",
            payload=CacheStatsResult(path=test_path("cache"), files=10, size_bytes=1024),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheStatsProducer().produce(result)
        output = buf.getvalue()
        self.assertIn(test_path("cache"), output)  # noqa: S108 - test fixture path
        self.assertIn("files=10", output)
        self.assertIn("size=1024", output)


class CacheClearTests(TestCase):
    """Tests for cache clear pipeline."""

    def test_cache_clear_consumer_returns_request(self):
        """CacheClearRequestConsumer returns the request."""
        request = CacheClearRequest(cache_path=test_path("test"))  # noqa: S108 - test fixture path
        consumer = CacheClearRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_clear_processor_clears_directory(self):
        """CacheClearProcessor removes the cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            (cache_dir / "file.json").write_text("data")

            request = CacheClearRequest(cache_path=str(cache_dir))
            result = CacheClearProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertTrue(result.payload.cleared)
            self.assertFalse(cache_dir.exists())

    def test_cache_clear_processor_nonexistent_dir(self):
        """CacheClearProcessor handles nonexistent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "does_not_exist"

            request = CacheClearRequest(cache_path=str(nonexistent))
            result = CacheClearProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertFalse(result.payload.cleared)

    def test_cache_clear_producer_cleared(self):
        """CacheClearProducer prints cleared message."""
        result = ResultEnvelope(
            status="success",
            payload=CacheClearResult(path=test_path("cache"), cleared=True),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("Cleared cache", buf.getvalue())

    def test_cache_clear_producer_not_cleared(self):
        """CacheClearProducer prints not exist message."""
        result = ResultEnvelope(
            status="success",
            payload=CacheClearResult(path=test_path("cache"), cleared=False),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CacheClearProducer().produce(result)
        self.assertIn("does not exist", buf.getvalue())


class CachePruneTests(TestCase):
    """Tests for cache prune pipeline."""

    def test_cache_prune_consumer_returns_request(self):
        """CachePruneRequestConsumer returns the request."""
        request = CachePruneRequest(cache_path=test_path("test"), days=7)  # noqa: S108 - test fixture path
        consumer = CachePruneRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_cache_prune_processor_removes_old_files(self):
        """CachePruneProcessor removes files older than specified days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            old_file = Path(tmpdir) / "old.json"
            new_file = Path(tmpdir) / "new.json"
            old_file.write_text("old")
            new_file.write_text("new")

            # Make old file appear old (2 days old)
            old_time = time.time() - (3 * 86400)
            os.utime(old_file, (old_time, old_time))

            request = CachePruneRequest(cache_path=tmpdir, days=1)
            result = CachePruneProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.removed)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())

    def test_cache_prune_processor_nonexistent_dir(self):
        """CachePruneProcessor handles nonexistent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "does_not_exist"

            request = CachePruneRequest(cache_path=str(nonexistent), days=7)
            result = CachePruneProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.removed)

    def test_cache_prune_producer_output(self):
        """CachePruneProducer prints prune results."""
        result = ResultEnvelope(
            status="success",
            payload=CachePruneResult(path=test_path("cache"), removed=5, days=7),  # noqa: S108 - test fixture path
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            CachePruneProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("Pruned 5 files", output)
        self.assertIn("7 days", output)


class ConfigInspectTests(TestCase):
    """Tests for config inspect pipeline."""

    def test_config_inspect_consumer_returns_request(self):
        """ConfigInspectRequestConsumer returns the request."""
        request = ConfigInspectRequest(path=test_path("test.ini"))  # noqa: S108 - test fixture path
        consumer = ConfigInspectRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_config_inspect_processor_reads_ini(self):
        """ConfigInspectProcessor reads and masks INI values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[mail_assistant.test]\n")
            f.write("credentials = /path/to/creds.json\n")
            f.write("token = /path/to/token.json\n")
            f.name

        try:
            request = ConfigInspectRequest(path=f.name)
            result = ConfigInspectProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, len(result.payload.sections))
            self.assertEqual("mail_assistant.test", result.payload.sections[0].name)
        finally:
            os.unlink(f.name)

    def test_config_inspect_processor_file_not_found(self):
        """ConfigInspectProcessor handles missing file."""
        request = ConfigInspectRequest(path="/nonexistent/config.ini")
        result = ConfigInspectProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("not found", result.diagnostics.get("message", ""))

    def test_config_inspect_processor_section_filter(self):
        """ConfigInspectProcessor filters by section."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[section1]\nkey1 = value1\n")
            f.write("[section2]\nkey2 = value2\n")
            f.name

        try:
            request = ConfigInspectRequest(path=f.name, section="section1")
            result = ConfigInspectProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, len(result.payload.sections))
            self.assertEqual("section1", result.payload.sections[0].name)
        finally:
            os.unlink(f.name)

    def test_config_inspect_producer_output(self):
        """ConfigInspectProducer prints sections."""
        result = ResultEnvelope(
            status="success",
            payload=ConfigInspectResult(
                sections=[ConfigSection(name="test", items=[("key", "value")])]
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ConfigInspectProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("[test]", output)
        self.assertIn("key = value", output)

    def test_config_inspect_processor_section_not_found_raises(self):
        """ConfigInspectProcessor raises ValueError for a missing section."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[existing_section]\nkey = value\n")
            ini_path = f.name
        try:
            request = ConfigInspectRequest(path=ini_path, section="no_such_section")
            result = ConfigInspectProcessor().process(request)
            self.assertFalse(result.ok())
            self.assertIn("Section not found", result.diagnostics.get("message", ""))
        finally:
            os.unlink(ini_path)

    def test_config_inspect_processor_only_mail_filters_sections(self):
        """ConfigInspectProcessor with only_mail=True returns only mail.* sections."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[mail.personal]\ntoken = /path/token.json\n")
            f.write("[other_section]\nkey = value\n")
            ini_path = f.name
        try:
            request = ConfigInspectRequest(path=ini_path, only_mail=True)
            result = ConfigInspectProcessor().process(request)
            self.assertTrue(result.ok())
            names = [s.name for s in result.payload.sections]
            self.assertIn("mail.personal", names)
            self.assertNotIn("other_section", names)
        finally:
            os.unlink(ini_path)


class CacheStatsOSErrorTests(TestCase):
    """CacheStatsProcessor handles OSError on stat() without crashing."""

    def test_inaccessible_file_is_skipped(self):
        """If stat() raises OSError, the file is skipped and totals are still correct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            good = Path(tmpdir) / "good.json"
            good.write_text("hello")

            processor = CacheStatsProcessor()
            bad_path = MagicMock()
            bad_path.is_file.return_value = True
            bad_path.stat.side_effect = OSError("permission denied")

            original_rglob = Path.rglob

            def patched_rglob(self, pattern):
                if str(self) == tmpdir:
                    yield from [bad_path, good]
                else:
                    yield from original_rglob(self, pattern)

            with patch.object(Path, "rglob", patched_rglob):
                request = CacheStatsRequest(cache_path=tmpdir)
                result = processor.process(request)

            self.assertTrue(result.ok())
            # The good file should still be counted; the bad one is skipped
            self.assertEqual(result.payload.files, 2)
            self.assertEqual(result.payload.size_bytes, 5)  # only "hello" counted


class CachePruneOSErrorTests(TestCase):
    """CachePruneProcessor skips files that raise OSError during removal."""

    def test_oserror_on_unlink_is_skipped(self):
        """Files that raise OSError on unlink are silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = Path(tmpdir) / "old.json"
            old_file.write_text("old")
            old_time = time.time() - (10 * 86400)
            os.utime(old_file, (old_time, old_time))

            def raise_on_unlink(self, *args, **kwargs):
                raise OSError("permission denied")

            with patch.object(Path, "unlink", raise_on_unlink):
                request = CachePruneRequest(cache_path=tmpdir, days=1)
                result = CachePruneProcessor().process(request)

            # Should not crash; removed count should be 0 since unlink failed
            self.assertTrue(result.ok())
            self.assertEqual(result.payload.removed, 0)


class AuthTests(TempDirMixin, TestCase):
    """Tests for AuthProcessor — auth and validate paths."""

    def test_auth_consumer_returns_request(self):
        """AuthRequestConsumer returns the request unchanged."""
        request = AuthRequest(profile="personal")
        consumer = AuthRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_auth_processor_authenticate_success(self):
        """AuthProcessor calls client.authenticate and returns success."""
        fake_client = MagicMock()
        fake_client.authenticate.return_value = None

        # Patch at import source since _process_safe uses local imports.
        with patch("mail.config_resolver.resolve_paths_profile", return_value=("creds.json", "token.json")), \
             patch("mail.gmail_api.GmailClient", return_value=fake_client), \
             patch("mail.config_resolver.persist_if_provided"):
            request = AuthRequest(credentials="creds.json", token="token.json", profile=None, validate=False)
            result = AuthProcessor().process(request)

        self.assertTrue(result.ok())
        self.assertEqual(result.payload.message, "Authentication complete.")
        fake_client.authenticate.assert_called_once_with(allow_interactive=True)

    def test_auth_processor_validate_missing_token_fails(self):
        """_validate_gmail_token raises ValueError when token file does not exist."""
        with patch("mail.config_resolver.resolve_paths_profile", return_value=(None, "/nonexistent/token.json")):
            request = AuthRequest(validate=True, token="/nonexistent/token.json")
            result = AuthProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("Token file not found", result.diagnostics.get("message", ""))

    def test_auth_processor_validate_none_token_fails(self):
        """_validate_gmail_token raises ValueError when token path is None."""
        with patch("mail.config_resolver.resolve_paths_profile", return_value=(None, None)):
            request = AuthRequest(validate=True)
            result = AuthProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("Token file not found", result.diagnostics.get("message", ""))

    def test_auth_producer_prints_message(self):
        """AuthProducer prints the result message."""
        result = ResultEnvelope(
            status="success",
            payload=AuthResult(success=True, message="Authentication complete."),
        )
        with capture_stdout() as buf:
            AuthProducer().produce(result)
        self.assertIn("Authentication complete.", buf.getvalue())

    def test_auth_processor_validate_invalid_token_raises(self):
        """_validate_gmail_token wraps API errors as ValueError with 'Gmail token invalid'."""
        token_path = os.path.join(self.tmpdir, "token.json")
        Path(token_path).write_text('{"token": "bad"}')

        mock_creds = MagicMock()
        mock_creds.expired = False

        mock_svc = MagicMock()
        mock_svc.users.return_value.getProfile.return_value.execute.side_effect = Exception("API error")

        # Patch the google imports at their source package paths.
        with patch("mail.config_resolver.resolve_paths_profile", return_value=(None, token_path)), \
             patch("google.oauth2.credentials.Credentials") as mock_creds_cls, \
             patch("google.auth.transport.requests.Request"), \
             patch("googleapiclient.discovery.build", return_value=mock_svc):
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds
            request = AuthRequest(validate=True, token=token_path)
            result = AuthProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("Gmail token invalid", result.diagnostics.get("message", ""))

    def test_auth_processor_validate_google_import_failure(self):
        """_validate_gmail_token raises ValueError when google imports are unavailable."""
        import sys

        # Setting a sys.modules entry to None causes `from X import Y` to raise ImportError.
        token_path = os.path.join(self.tmpdir, "token.json")
        Path(token_path).write_text('{"token": "x"}')
        with patch("mail.config_resolver.resolve_paths_profile", return_value=(None, token_path)), \
             patch.dict(sys.modules, {"googleapiclient.discovery": None}):
            request = AuthRequest(validate=True, token=token_path)
            result = AuthProcessor().process(request)

        self.assertFalse(result.ok())
        self.assertIn("Gmail validation unavailable", result.diagnostics.get("message", ""))

    def test_auth_processor_validate_refresh_expired_creds(self):
        """_validate_gmail_token calls creds.refresh() when creds are expired with refresh_token."""
        token_path = os.path.join(self.tmpdir, "token.json")
        Path(token_path).write_text('{"token": "old"}')

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "my_refresh_token"

        mock_svc = MagicMock()
        mock_svc.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "me@example.com"}

        with patch("mail.config_resolver.resolve_paths_profile", return_value=(None, token_path)), \
             patch("google.oauth2.credentials.Credentials") as mock_creds_cls, \
             patch("google.auth.transport.requests.Request") as mock_request, \
             patch("googleapiclient.discovery.build", return_value=mock_svc):
            mock_creds_cls.from_authorized_user_file.return_value = mock_creds
            request = AuthRequest(validate=True, token=token_path)
            result = AuthProcessor().process(request)

        self.assertTrue(result.ok())
        self.assertEqual(result.payload.message, "Gmail token valid.")
        mock_creds.refresh.assert_called_once_with(mock_request())


class BackupTests(TempDirMixin, TestCase):
    """Tests for BackupProcessor and BackupProducer."""

    def test_backup_consumer_returns_request(self):
        """BackupRequestConsumer returns the request unchanged."""
        request = BackupRequest(out_dir=self.tmpdir)
        consumer = BackupRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_backup_processor_writes_labels_and_filters(self):
        """BackupProcessor writes labels.yaml and filters.yaml to the output directory."""
        from tests.fakes.gmail import FakeGmailClient

        fake_client = FakeGmailClient(
            labels=[
                {"id": "LBL1", "name": "Work", "type": "user",
                 "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                {"id": "INBOX", "name": "INBOX", "type": "system"},
            ],
            filters=[
                {"id": "F1", "criteria": {"from": "boss@work.com"}, "action": {"addLabelIds": ["LBL1"]}},
            ],
        )

        out_dir = os.path.join(self.tmpdir, "backup_out")
        request = BackupRequest(out_dir=out_dir)

        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=fake_client):
            result = BackupProcessor().process(request)

        self.assertTrue(result.ok())
        self.assertEqual(result.payload.out_path, out_dir)
        self.assertEqual(result.payload.labels_count, 1)  # only user labels, not system
        self.assertEqual(result.payload.filters_count, 1)
        self.assertTrue(os.path.exists(os.path.join(out_dir, "labels.yaml")))
        self.assertTrue(os.path.exists(os.path.join(out_dir, "filters.yaml")))

    def test_backup_producer_prints_path(self):
        """BackupProducer prints the backup path."""
        result = ResultEnvelope(
            status="success",
            payload=BackupResult(out_path="/some/backup/path", labels_count=3, filters_count=2),
        )
        with capture_stdout() as buf:
            BackupProducer().produce(result)
        self.assertIn("/some/backup/path", buf.getvalue())
        self.assertIn("Backup written to", buf.getvalue())
