"""WhatsApp domain test fixtures and factories.

Domain-specific helpers for whatsapp tests.  Import from here rather than
constructing MagicMock args inline — keeps all default values in one place
so that a field rename only needs one fix.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def make_mock_search_args(**overrides) -> MagicMock:
    """Return a MagicMock pre-configured to look like parsed search args.

    All fields mirror the argparse namespace produced by cmd_search:
      from_me, from_them, db, contains, match_all, match_any,
      contact, since_days, limit, json.

    Pass keyword arguments to override any default:

        args = make_mock_search_args(from_me=True, contains=["hello"])
    """
    args = MagicMock()
    args.from_me = overrides.get("from_me", False)
    args.from_them = overrides.get("from_them", False)
    args.db = overrides.get("db", None)
    args.contains = overrides.get("contains", [])
    args.match_all = overrides.get("match_all", False)
    args.match_any = overrides.get("match_any", False)
    args.contact = overrides.get("contact", None)
    args.since_days = overrides.get("since_days", None)
    args.limit = overrides.get("limit", 50)
    args.json = overrides.get("json", False)
    return args
