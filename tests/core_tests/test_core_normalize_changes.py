"""Tests covering the design-criteria-normalize changes to src/core/.

C1 — OutputConfig backward-compat alias
C3 — OutlookBaseProvider Protocol conformance
C7 — build_outlook_service consumes OutlookServiceConfig directly
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestOutputConfigAlias(unittest.TestCase):
    """C1: OutputConfig is an alias for OutputFormatConfig (identity, not just equality)."""

    def test_output_config_is_output_format_config(self):
        """OutputConfig and OutputFormatConfig must be the exact same object."""
        from core.cli_args import OutputConfig, OutputFormatConfig
        self.assertIs(OutputConfig, OutputFormatConfig)

    def test_output_config_instances_are_output_format_config(self):
        """Instances constructed via the alias are OutputFormatConfig instances."""
        from core.cli_args import OutputConfig, OutputFormatConfig
        obj = OutputConfig()
        self.assertIsInstance(obj, OutputFormatConfig)

    def test_output_config_fields_accessible(self):
        """OutputConfig exposes the same fields as OutputFormatConfig."""
        from core.cli_args import OutputConfig
        cfg = OutputConfig(formats=["text", "json"], default_format="json")
        self.assertEqual(cfg.default_format, "json")
        self.assertEqual(cfg.formats, ["text", "json"])


class TestOutlookBaseProviderProtocol(unittest.TestCase):
    """C3: OutlookBaseProvider runtime-checkable Protocol."""

    def test_conforming_class_satisfies_protocol(self):
        """A class with get_service() satisfies OutlookBaseProvider via isinstance."""
        from core.outlook.base import OutlookBaseProvider

        class MyProvider:
            def get_service(self):
                return object()

        provider = MyProvider()
        self.assertIsInstance(provider, OutlookBaseProvider)

    def test_non_conforming_class_fails_isinstance(self):
        """A class without get_service() does NOT satisfy OutlookBaseProvider."""
        from core.outlook.base import OutlookBaseProvider

        class NotAProvider:
            pass

        self.assertNotIsInstance(NotAProvider(), OutlookBaseProvider)

    def test_protocol_exported_from_package(self):
        """OutlookBaseProvider is exported from core.outlook.__init__."""
        from core import outlook as pkg
        self.assertIn("OutlookBaseProvider", pkg.__all__)

    def test_provider_get_service_callable(self):
        """get_service() on a conforming object returns a value."""
        from core.outlook.base import OutlookBaseProvider

        sentinel = object()

        class ConcreteProvider:
            def get_service(self):
                return sentinel

        provider = ConcreteProvider()
        self.assertIsInstance(provider, OutlookBaseProvider)
        self.assertIs(provider.get_service(), sentinel)


class TestBuildOutlookServiceConsolidation(unittest.TestCase):
    """C7: build_outlook_service consumes an OutlookServiceConfig directly."""

    def _make_stubs(self):
        """Return (mock_context_cls, mock_service_cls, mock_service_instance)."""
        mock_service = MagicMock()
        mock_service_cls = MagicMock(return_value=mock_service)
        mock_context_cls = MagicMock()
        return mock_context_cls, mock_service_cls, mock_service

    @patch("core.auth.resolve_outlook_credentials")
    def test_build_outlook_service_uses_resolved_credentials(self, mock_resolve):
        """build_outlook_service() passes resolved creds to the context class."""
        from core.auth import OutlookServiceConfig, build_outlook_service

        mock_resolve.return_value = ("cid", "tenant", "/tok.json")
        mock_context_cls, mock_service_cls, _ = self._make_stubs()

        build_outlook_service(
            OutlookServiceConfig(profile="p", client_id="cid", tenant="t", token_path="/t.json"),  # nosec B106 - test fixture path, not a credential
            context_cls=mock_context_cls,
            service_cls=mock_service_cls,
        )

        mock_resolve.assert_called_once_with("p", "cid", "t", "/t.json")
        mock_context_cls.assert_called_once_with(
            client_id="cid", tenant="tenant", token_path="/tok.json", profile="p"  # nosec B106 - test fixture path, not a credential
        )
        mock_service_cls.assert_called_once()

    @patch("core.auth.resolve_outlook_credentials")
    def test_build_outlook_service_invokes_service_cls_with_context(self, mock_resolve):
        """build_outlook_service() wraps the resolved context in the service class."""
        from core.auth import OutlookServiceConfig, build_outlook_service

        mock_resolve.return_value = ("cid3", "t3", "/tok3.json")

        calls = []

        def tracking_context_cls(**kw):
            calls.append(kw)
            return MagicMock()

        mock_svc = MagicMock(return_value=MagicMock())

        build_outlook_service(
            OutlookServiceConfig(profile="x", client_id="cid3", tenant="t3", token_path="/tok3.json"),  # nosec B106 - test fixture path, not a credential
            context_cls=tracking_context_cls,
            service_cls=mock_svc,
        )

        self.assertEqual(
            calls,
            [{"client_id": "cid3", "tenant": "t3", "token_path": "/tok3.json", "profile": "x"}],
        )
        mock_svc.assert_called_once()


if __name__ == "__main__":
    unittest.main()
