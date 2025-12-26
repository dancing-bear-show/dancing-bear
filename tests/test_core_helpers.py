import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.fixtures import has_pyyaml


class CorePipelineTests(unittest.TestCase):
    def test_result_envelope_ok_case_insensitive(self):
        from core.pipeline import ResultEnvelope

        self.assertTrue(ResultEnvelope(status="success").ok())
        self.assertTrue(ResultEnvelope(status="SUCCESS").ok())
        self.assertFalse(ResultEnvelope(status="error").ok())


class CoreContextTests(unittest.TestCase):
    def test_resolve_joins_root(self):
        from core.context import AppContext

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = AppContext(root=root, config={}, args=object())
            self.assertEqual(ctx.resolve("foo/bar"), (root / "foo" / "bar").resolve())


class CoreTextIOTests(unittest.TestCase):
    def test_read_text_missing_default(self):
        from core.textio import read_text

        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.txt"
            self.assertEqual(read_text(missing, default="fallback"), "fallback")

    def test_write_text_creates_parent(self):
        from core.textio import read_text, write_text

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "nested" / "file.txt"
            write_text(target, "hello")
            self.assertTrue(target.exists())
            self.assertEqual(read_text(target), "hello")


class CoreCliArgsTests(unittest.TestCase):
    def test_add_outlook_auth_args_tenant_none(self):
        from core.cli_args import add_outlook_auth_args

        parser = argparse.ArgumentParser()
        add_outlook_auth_args(parser, include_profile=True, tenant_default=None)
        args = parser.parse_args([])
        self.assertIsNone(args.tenant)
        self.assertIsNone(args.profile)

    def test_add_gmail_auth_args_includes_cache(self):
        from core.cli_args import add_gmail_auth_args

        parser = argparse.ArgumentParser()
        add_gmail_auth_args(parser, include_cache=True)
        args = parser.parse_args(["--cache", "tmp"])
        self.assertEqual(args.cache, "tmp")


class CoreAssistantTests(unittest.TestCase):
    def test_add_agentic_flags_parses(self):
        from core.assistant import BaseAssistant

        parser = argparse.ArgumentParser()
        BaseAssistant("demo", "fallback").add_agentic_flags(parser)
        args = parser.parse_args(["--agentic", "--agentic-format", "yaml", "--agentic-compact"])
        self.assertTrue(args.agentic)
        self.assertEqual(args.agentic_format, "yaml")
        self.assertTrue(args.agentic_compact)

    def test_maybe_emit_agentic_disabled(self):
        from core.assistant import BaseAssistant

        assistant = BaseAssistant("demo", "fallback")
        args = SimpleNamespace(agentic=False)
        self.assertIsNone(assistant.maybe_emit_agentic(args, lambda *_: 1))

    def test_maybe_emit_agentic_calls_emit_func(self):
        from core.assistant import BaseAssistant

        seen = {}

        def emit(fmt, compact):
            seen["fmt"] = fmt
            seen["compact"] = compact
            return 7

        assistant = BaseAssistant("demo", "fallback")
        args = SimpleNamespace(agentic=True, agentic_format="yaml", agentic_compact=True)
        rc = assistant.maybe_emit_agentic(args, emit)
        self.assertEqual(rc, 7)
        self.assertEqual(seen, {"fmt": "yaml", "compact": True})

    def test_maybe_emit_agentic_typeerror_fallback(self):
        from core.assistant import BaseAssistant

        def emit():
            return 5

        assistant = BaseAssistant("demo", "fallback")
        args = SimpleNamespace(agentic=True, agentic_format="text", agentic_compact=False)
        rc = assistant.maybe_emit_agentic(args, emit)
        self.assertEqual(rc, 5)

    def test_maybe_emit_agentic_exception_fallback(self):
        from core.assistant import BaseAssistant

        def emit(*_args, **_kwargs):
            raise ValueError("boom")

        assistant = BaseAssistant("demo", "fallback banner")
        args = SimpleNamespace(agentic=True, agentic_format="text", agentic_compact=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = assistant.maybe_emit_agentic(args, emit)
        self.assertEqual(rc, 0)
        self.assertIn("fallback banner", buf.getvalue())


class CoreAuthTests(unittest.TestCase):
    def test_resolve_outlook_credentials_env_override(self):
        from core import auth as core_auth

        with patch.dict(
            os.environ,
            {
                "MAIL_ASSISTANT_OUTLOOK_CLIENT_ID": "env_client",
                "MAIL_ASSISTANT_OUTLOOK_TENANT": "env_tenant",
            },
        ):
            with patch("mail.config_resolver.get_outlook_client_id", return_value="profile_client"), \
                 patch("mail.config_resolver.get_outlook_tenant", return_value="profile_tenant"), \
                 patch("mail.config_resolver.get_outlook_token_path", return_value="~/token.json"):
                client, tenant, token = core_auth.resolve_outlook_credentials(None, None, None, None)

        self.assertEqual(client, "env_client")
        self.assertEqual(tenant, "env_tenant")
        self.assertEqual(token, os.path.expanduser("~/token.json"))

    def test_resolve_outlook_credentials_args_override(self):
        from core import auth as core_auth

        with patch.dict(
            os.environ,
            {
                "MAIL_ASSISTANT_OUTLOOK_CLIENT_ID": "env_client",
                "MAIL_ASSISTANT_OUTLOOK_TENANT": "env_tenant",
            },
        ):
            with patch("mail.config_resolver.get_outlook_client_id", return_value="profile_client"), \
                 patch("mail.config_resolver.get_outlook_tenant", return_value="profile_tenant"), \
                 patch("mail.config_resolver.get_outlook_token_path", return_value="~/token.json"):
                client, tenant, token = core_auth.resolve_outlook_credentials(
                    "profile", "cli_client", "cli_tenant", "/tmp/token.json"
                )

        self.assertEqual(client, "cli_client")
        self.assertEqual(tenant, "cli_tenant")
        self.assertEqual(token, "/tmp/token.json")

    def test_build_outlook_service_from_args_passes_values(self):
        from core import auth as core_auth

        class DummyContext:
            def __init__(self, client_id, tenant, token_path, profile):
                self.client_id = client_id
                self.tenant = tenant
                self.token_path = token_path
                self.profile = profile

        class DummyService:
            def __init__(self, ctx):
                self.ctx = ctx

        args = SimpleNamespace(profile="profile", client_id="cli_id", tenant="cli_tenant", token="cli_token")  # noqa: S106
        with patch("core.auth.resolve_outlook_credentials", return_value=("cid", "ten", "tok")) as mocked:
            svc = core_auth.build_outlook_service_from_args(
                args,
                context_cls=DummyContext,
                service_cls=DummyService,
            )
        mocked.assert_called_once_with("profile", "cli_id", "cli_tenant", "cli_token")
        self.assertEqual(svc.ctx.client_id, "cid")
        self.assertEqual(svc.ctx.tenant, "ten")
        self.assertEqual(svc.ctx.token_path, "tok")
        self.assertEqual(svc.ctx.profile, "profile")

    def test_build_gmail_service_from_args_passes_values(self):
        from core import auth as core_auth

        class DummyService:
            seen_args = None

            @classmethod
            def from_args(cls, args):
                cls.seen_args = args
                return cls()

            def authenticate(self):
                self.authed = True

        args = SimpleNamespace(profile="profile", credentials="cred", token="tok", cache="cache")  # noqa: S106
        svc = core_auth.build_gmail_service_from_args(args, service_cls=DummyService)
        self.assertTrue(getattr(svc, "authed", False))
        self.assertEqual(DummyService.seen_args.profile, "profile")
        self.assertEqual(DummyService.seen_args.credentials, "cred")
        self.assertEqual(DummyService.seen_args.token, "tok")
        self.assertEqual(DummyService.seen_args.cache, "cache")


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class CoreYamlIOTests(unittest.TestCase):
    def test_load_config_missing_returns_empty(self):
        from core.yamlio import load_config

        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.yaml"
            self.assertEqual(load_config(str(missing)), {})

    def test_dump_and_load_roundtrip(self):
        from core.yamlio import dump_config, load_config

        data = {"events": [{"subject": "Event", "start": "2025-01-01T10:00:00"}]}
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "plan.yaml"
            dump_config(str(target), data)
            self.assertTrue(target.exists())
            loaded = load_config(str(target))
            self.assertEqual(loaded, data)

    def test_load_config_allows_non_dict(self):
        from core.yamlio import load_config

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "list.yaml"
            target.write_text("- one\n- two\n", encoding="utf-8")
            loaded = load_config(str(target))
            self.assertEqual(loaded, ["one", "two"])


if __name__ == "__main__":
    unittest.main()
