"""Tests for mail/signatures/commands.py and consumers.py."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_args(**kwargs):
    defaults = {
        "credentials": None,
        "token": None,
        "cache": None,
        "profile": None,
        "out": "/tmp/signatures.yaml",
        "assets_dir": "/tmp/assets",
        "config": "/tmp/sig_config.yaml",
        "dry_run": False,
        "send_as": None,
        "account_display_name": None,
        "out_html": "/tmp/sig.html",
        "var": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_ok_envelope():
    env = MagicMock()
    env.ok.return_value = True
    env.diagnostics = {}
    return env


def _make_error_envelope(code=1):
    env = MagicMock()
    env.ok.return_value = False
    env.diagnostics = {"code": code}
    return env


class TestRunSignaturesExport(unittest.TestCase):
    """Tests for run_signatures_export."""

    @patch("mail.signatures.commands.SignaturesExportProducer")
    @patch("mail.signatures.commands.SignaturesExportProcessor")
    @patch("mail.signatures.commands.SignaturesExportConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_export
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_signatures_export(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.signatures.commands.SignaturesExportProducer")
    @patch("mail.signatures.commands.SignaturesExportProcessor")
    @patch("mail.signatures.commands.SignaturesExportConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_returns_nonzero_on_error(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_export
        envelope = _make_error_envelope(code=2)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_signatures_export(_make_args())
        self.assertEqual(result, 2)

    @patch("mail.signatures.commands.SignaturesExportProducer")
    @patch("mail.signatures.commands.SignaturesExportProcessor")
    @patch("mail.signatures.commands.SignaturesExportConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_consumer_receives_correct_paths(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_export
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        fake_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = fake_ctx

        args = _make_args(out="/tmp/sigs.yaml", assets_dir="/tmp/my_assets")
        run_signatures_export(args)

        mock_consumer_cls.assert_called_once_with(
            context=fake_ctx,
            out_path=Path("/tmp/sigs.yaml"),
            assets_dir=Path("/tmp/my_assets"),
        )

    @patch("mail.signatures.commands.SignaturesExportProducer")
    @patch("mail.signatures.commands.SignaturesExportProcessor")
    @patch("mail.signatures.commands.SignaturesExportConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_pipeline_produces_with_envelope(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_export
        envelope = _make_ok_envelope()
        payload = MagicMock()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = payload
        mock_ctx_cls.from_args.return_value = MagicMock()

        run_signatures_export(_make_args())

        mock_producer_cls.return_value.produce.assert_called_once_with(envelope)


class TestRunSignaturesSync(unittest.TestCase):
    """Tests for run_signatures_sync."""

    @patch("mail.signatures.commands.SignaturesSyncProducer")
    @patch("mail.signatures.commands.SignaturesSyncProcessor")
    @patch("mail.signatures.commands.SignaturesSyncConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_sync
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_signatures_sync(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.signatures.commands.SignaturesSyncProducer")
    @patch("mail.signatures.commands.SignaturesSyncProcessor")
    @patch("mail.signatures.commands.SignaturesSyncConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_returns_nonzero_on_error(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_sync
        envelope = _make_error_envelope(code=3)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        result = run_signatures_sync(_make_args())
        self.assertEqual(result, 3)

    @patch("mail.signatures.commands.SignaturesSyncProducer")
    @patch("mail.signatures.commands.SignaturesSyncProcessor")
    @patch("mail.signatures.commands.SignaturesSyncConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_consumer_receives_dry_run_and_send_as(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_sync
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        fake_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = fake_ctx

        args = _make_args(dry_run=True, send_as="user@example.com", account_display_name="User")
        run_signatures_sync(args)

        call_kwargs = mock_consumer_cls.call_args.kwargs
        self.assertEqual(call_kwargs["context"], fake_ctx)
        self.assertTrue(call_kwargs["dry_run"])
        self.assertEqual(call_kwargs["send_as"], "user@example.com")
        self.assertEqual(call_kwargs["account_display_name"], "User")

    @patch("mail.signatures.commands.SignaturesSyncProducer")
    @patch("mail.signatures.commands.SignaturesSyncProcessor")
    @patch("mail.signatures.commands.SignaturesSyncConsumer")
    @patch("mail.signatures.commands.MailContext")
    def test_sync_with_no_optional_args(self, mock_ctx_cls, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        """Args without send_as/account_display_name default to None."""
        from mail.signatures.commands import run_signatures_sync
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()
        mock_ctx_cls.from_args.return_value = MagicMock()

        args = SimpleNamespace(
            credentials=None, token=None, cache=None, profile=None,
            config="/tmp/sig.yaml"
        )
        run_signatures_sync(args)

        call_kwargs = mock_consumer_cls.call_args.kwargs
        self.assertIsNone(call_kwargs["send_as"])
        self.assertIsNone(call_kwargs["account_display_name"])
        self.assertFalse(call_kwargs["dry_run"])


class TestRunSignaturesNormalize(unittest.TestCase):
    """Tests for run_signatures_normalize."""

    @patch("mail.signatures.commands.SignaturesNormalizeProducer")
    @patch("mail.signatures.commands.SignaturesNormalizeProcessor")
    @patch("mail.signatures.commands.SignaturesNormalizeConsumer")
    def test_returns_zero_on_success(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_normalize
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        result = run_signatures_normalize(_make_args())
        self.assertEqual(result, 0)

    @patch("mail.signatures.commands.SignaturesNormalizeProducer")
    @patch("mail.signatures.commands.SignaturesNormalizeProcessor")
    @patch("mail.signatures.commands.SignaturesNormalizeConsumer")
    def test_returns_nonzero_on_error(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_normalize
        envelope = _make_error_envelope(code=4)
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        result = run_signatures_normalize(_make_args())
        self.assertEqual(result, 4)

    @patch("mail.signatures.commands.SignaturesNormalizeProducer")
    @patch("mail.signatures.commands.SignaturesNormalizeProcessor")
    @patch("mail.signatures.commands.SignaturesNormalizeConsumer")
    def test_consumer_receives_correct_params(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        from mail.signatures.commands import run_signatures_normalize
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        args = _make_args(config="/tmp/sig.yaml", out_html="/tmp/sig.html", var=["name=John"])
        run_signatures_normalize(args)

        mock_consumer_cls.assert_called_once_with(
            config_path="/tmp/sig.yaml",
            out_html=Path("/tmp/sig.html"),
            variables=["name=John"],
        )

    @patch("mail.signatures.commands.SignaturesNormalizeProducer")
    @patch("mail.signatures.commands.SignaturesNormalizeProcessor")
    @patch("mail.signatures.commands.SignaturesNormalizeConsumer")
    def test_var_defaults_to_empty_list(self, mock_consumer_cls, mock_processor_cls, mock_producer_cls):
        """When var is None, defaults to empty list."""
        from mail.signatures.commands import run_signatures_normalize
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        mock_consumer_cls.return_value.consume.return_value = MagicMock()

        args = SimpleNamespace(
            config="/tmp/sig.yaml",
            out_html="/tmp/sig.html",
        )
        run_signatures_normalize(args)

        call_kwargs = mock_consumer_cls.call_args.kwargs
        self.assertEqual(call_kwargs["variables"], [])


class TestSignaturesExportConsumer(unittest.TestCase):
    """Tests for SignaturesExportConsumer."""

    def test_consume_returns_payload(self):
        from mail.signatures.consumers import SignaturesExportConsumer, SignaturesExportPayload
        ctx = MagicMock()
        consumer = SignaturesExportConsumer(
            context=ctx,
            out_path=Path("/tmp/out.yaml"),
            assets_dir=Path("/tmp/assets"),
        )
        payload = consumer.consume()
        self.assertIsInstance(payload, SignaturesExportPayload)
        self.assertEqual(payload.context, ctx)
        self.assertEqual(payload.out_path, Path("/tmp/out.yaml"))
        self.assertEqual(payload.assets_dir, Path("/tmp/assets"))


class TestSignaturesSyncConsumer(unittest.TestCase):
    """Tests for SignaturesSyncConsumer."""

    def test_consume_loads_config(self):
        from mail.signatures.consumers import SignaturesSyncConsumer, SignaturesSyncPayload
        ctx = MagicMock()

        with patch("mail.signatures.consumers.load_config", return_value={"signatures": {}}) as mock_load:
            consumer = SignaturesSyncConsumer(
                context=ctx,
                config_path="/tmp/config.yaml",
                dry_run=True,
                send_as="user@example.com",
            )
            payload = consumer.consume()

        mock_load.assert_called_once_with("/tmp/config.yaml")
        self.assertIsInstance(payload, SignaturesSyncPayload)
        self.assertTrue(payload.dry_run)
        self.assertEqual(payload.send_as, "user@example.com")
        self.assertEqual(payload.config, {"signatures": {}})

    def test_consume_defaults(self):
        from mail.signatures.consumers import SignaturesSyncConsumer
        ctx = MagicMock()

        with patch("mail.signatures.consumers.load_config", return_value={}):
            consumer = SignaturesSyncConsumer(context=ctx, config_path="/tmp/c.yaml")
            payload = consumer.consume()

        self.assertFalse(payload.dry_run)
        self.assertIsNone(payload.send_as)
        self.assertIsNone(payload.account_display_name)


class TestSignaturesNormalizeConsumer(unittest.TestCase):
    """Tests for SignaturesNormalizeConsumer."""

    def test_consume_parses_variables(self):
        from mail.signatures.consumers import SignaturesNormalizeConsumer, SignaturesNormalizePayload

        with patch("mail.signatures.consumers.load_config", return_value={"signatures": {}}):
            consumer = SignaturesNormalizeConsumer(
                config_path="/tmp/config.yaml",
                out_html=Path("/tmp/sig.html"),
                variables=["name=John", "company=Acme"],
            )
            payload = consumer.consume()

        self.assertIsInstance(payload, SignaturesNormalizePayload)
        self.assertEqual(payload.variables, {"name": "John", "company": "Acme"})
        self.assertEqual(payload.out_html, Path("/tmp/sig.html"))

    def test_consume_ignores_entries_without_equals(self):
        from mail.signatures.consumers import SignaturesNormalizeConsumer

        with patch("mail.signatures.consumers.load_config", return_value={}):
            consumer = SignaturesNormalizeConsumer(
                config_path="/tmp/config.yaml",
                out_html=Path("/tmp/sig.html"),
                variables=["no_equals_here", "valid=value"],
            )
            payload = consumer.consume()

        self.assertEqual(payload.variables, {"valid": "value"})

    def test_consume_handles_empty_variables(self):
        from mail.signatures.consumers import SignaturesNormalizeConsumer

        with patch("mail.signatures.consumers.load_config", return_value={}):
            consumer = SignaturesNormalizeConsumer(
                config_path="/tmp/config.yaml",
                out_html=Path("/tmp/sig.html"),
                variables=[],
            )
            payload = consumer.consume()

        self.assertEqual(payload.variables, {})

    def test_consume_splits_on_first_equals(self):
        from mail.signatures.consumers import SignaturesNormalizeConsumer

        with patch("mail.signatures.consumers.load_config", return_value={}):
            consumer = SignaturesNormalizeConsumer(
                config_path="/tmp/config.yaml",
                out_html=Path("/tmp/sig.html"),
                variables=["key=val=with=equals"],
            )
            payload = consumer.consume()

        self.assertEqual(payload.variables, {"key": "val=with=equals"})


if __name__ == "__main__":
    unittest.main()
