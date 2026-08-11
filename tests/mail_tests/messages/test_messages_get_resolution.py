"""Regression tests for `messages get` id/query resolution.

Guards the --ids comma-split contract: a list must NEVER reach
select_message_id, which treats any truthy --id as a scalar and hands it
straight to client.get_message. A list there is swallowed by the fallback and
returned as the id itself, producing a silently wrong answer rather than an
error -- so these assert the value's TYPE, not just the exit code.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import make_args
from tests.mail_tests.messages.test_messages_cli import _make_messages_client
from mail.messages_cli.commands import (
    _resolve_get_ids,
    parse_id_list,
    run_messages_get,
)


def _get_args(**kwargs):
    """Build `messages get` args with every selector defaulted off."""
    defaults = {
        "id": None,
        "ids": None,
        "query": None,
        "days": None,
        "only_inbox": False,
        "format": "text",
    }
    defaults.update(kwargs)
    return make_args(**defaults)


def _run_get(client, **overrides):
    """Run `messages get` against a fake client, returning (rc, stdout)."""
    with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
        with capture_stdout() as buf:
            rc = run_messages_get(_get_args(**overrides))
    return rc, buf.getvalue()


class ParseIdListTests(unittest.TestCase):
    def test_splits_and_strips(self):
        self.assertEqual(parse_id_list("A, B ,C"), ["A", "B", "C"])

    def test_drops_empty_segments(self):
        self.assertEqual(parse_id_list("A,,B,"), ["A", "B"])

    def test_blank_and_none_yield_empty_list(self):
        self.assertEqual(parse_id_list(None), [])
        self.assertEqual(parse_id_list("   "), [])

    def test_single_id_still_yields_a_list(self):
        self.assertEqual(parse_id_list("ONLY"), ["ONLY"])


class ResolveGetIdsTests(unittest.TestCase):
    """--ids never reaches select_message_id as a list."""

    def test_ids_never_reach_select_message_id(self):
        client = _make_messages_client()
        with patch("mail.messages_cli.commands.select_message_id") as sel:
            ids = _resolve_get_ids(_get_args(ids="A,B,C"), client)
        # Resolution short-circuits on --ids: the query path is never consulted.
        sel.assert_not_called()
        self.assertEqual(ids, ["A", "B", "C"])

    def test_query_path_receives_scalar_id_not_a_list(self):
        """When --query resolution runs, args.id must still be a scalar/None."""
        client = _make_messages_client()
        seen: dict = {}

        def _capture(args, _client):
            seen["id"] = getattr(args, "id", None)
            return "RESOLVED", "T1"

        with patch("mail.messages_cli.commands.select_message_id", side_effect=_capture):
            ids = _resolve_get_ids(_get_args(query="subject:hello"), client)

        self.assertEqual(ids, ["RESOLVED"])
        self.assertNotIsInstance(seen["id"], list)

    def test_ids_takes_precedence_over_id_and_query(self):
        client = _make_messages_client()
        ids = _resolve_get_ids(
            _get_args(ids="A,B", id="SCALAR", query="subject:hello"), client
        )
        self.assertEqual(ids, ["A", "B"])

    def test_scalar_id_takes_precedence_over_query(self):
        client = _make_messages_client()
        with patch("mail.messages_cli.commands.select_message_id") as sel:
            ids = _resolve_get_ids(_get_args(id="SCALAR", query="subject:hello"), client)
        sel.assert_not_called()
        self.assertEqual(ids, ["SCALAR"])


class MessagesGetCLITests(unittest.TestCase):
    def test_no_selector_exits_1(self):
        client = _make_messages_client()
        rc, _ = _run_get(client)
        self.assertEqual(rc, 1)

    def test_get_by_scalar_id(self):
        client = _make_messages_client()
        rc, out = _run_get(client, id="MSG1")
        self.assertEqual(rc, 0)
        self.assertIn("Hello", out)

    def test_get_by_query_resolves_a_message(self):
        client = _make_messages_client()
        rc, out = _run_get(client, query="subject:hello")
        self.assertEqual(rc, 0)
        self.assertIn("Hello", out)

    def test_single_id_json_is_a_bare_object(self):
        """Backwards compatibility: one id must not become a list."""
        client = _make_messages_client()
        rc, out = _run_get(client, id="MSG1", format="json")
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["id"], "MSG1")

    def test_multi_id_json_is_a_list(self):
        client = _make_messages_client()
        rc, out = _run_get(client, ids="MSG1,MSG1", format="json")
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_multi_id_text_separates_records(self):
        client = _make_messages_client()
        rc, out = _run_get(client, ids="MSG1,MSG1")
        self.assertEqual(rc, 0)
        self.assertIn("---", out)


if __name__ == "__main__":
    unittest.main()
