"""Shared Outlook test helpers — extracted from duplicate defs across:

  tests/core_tests/test_core_outlook_calendar.py
  tests/core_tests/test_core_outlook_mail.py
  tests/core_tests/test_outlook_mail_folders.py

Keeps mock-response builders and a common test base close to the outlook
integration tests without dragging a facade into the source tree.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock

import requests

from core.outlook.mail import OutlookMailMixin


def iso_days_ago(days: int) -> str:
    """Return an ISO-8601 Z timestamp ``days`` before now."""
    stamp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_mock_response(json_data=None, status_code=200, text=None):
    """Build a mock HTTP response object with an optional JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    fallback_text = str(json_data) if json_data else ""
    resp.text = text if text is not None else fallback_text
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def make_error_response(status_code=500, text="Internal Server Error"):
    """Build a mock HTTP response whose ``raise_for_status()`` raises HTTPError."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock(
        side_effect=requests.exceptions.HTTPError(f"{status_code} Error", response=resp)
    )
    return resp


class FakeMailClient(OutlookMailMixin):
    """Minimal fake client used to exercise ``OutlookMailMixin`` methods."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir
        self._cfg_cache: dict = {}

    def _headers(self):
        return {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}

    def _headers_search(self):
        h = self._headers()
        h["ConsistencyLevel"] = "eventual"
        return h

    def cfg_get_json(self, key, ttl=300):  # noqa: ARG002 - ttl unused in fake
        return self._cfg_cache.get(key)

    def cfg_put_json(self, key, data):
        self._cfg_cache[key] = data

    def cfg_clear(self):
        self._cfg_cache.clear()


class OutlookMailTestBase(unittest.TestCase):
    """Base class for Outlook mail tests with common request-mocking helper."""

    def _setup_mock_requests(self, mock_requests_fn):
        """Wire up ``mock_requests_fn`` and return the mock module surface."""
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        return mock_requests


class OutlookCalendarTestBase(unittest.TestCase):
    """Base class for Outlook calendar tests with the same helper as mail."""

    def _setup_mock_requests(self, mock_requests_fn):
        mock_requests = MagicMock()
        mock_requests_fn.return_value = mock_requests
        return mock_requests
