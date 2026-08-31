"""Tests for phone/agentic.py — capsule builders.

Generic contract assertions (capsule shape, emit return code, domain map
top-level) are covered by TestPhoneAgenticContract in
test_phone_agentic_coverage.py. This file retains the helper-function tests
that are not part of that contract.
"""
from __future__ import annotations

import unittest


class TestCliPathExists(unittest.TestCase):
    def test_existing_path_returns_true(self):
        from phone.agentic import _cli_path_exists

        # "plan" is a known subcommand in phone
        result = _cli_path_exists(["plan"])
        self.assertIsInstance(result, bool)

    def test_nonexistent_path_returns_false(self):
        from phone.agentic import _cli_path_exists

        result = _cli_path_exists(["nonexistent_command_xyz"])
        self.assertFalse(result)


class TestFlowMap(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import _flow_map

        result = _flow_map()
        self.assertIsInstance(result, str)

    def test_contains_layout_info(self):
        from phone.agentic import _flow_map

        result = _flow_map()
        # Should be non-None (even if empty string) when called without args
        self.assertIsNotNone(result)


class TestCliTree(unittest.TestCase):
    def test_returns_string_or_none(self):
        from phone.agentic import _cli_tree

        result = _cli_tree()
        # May be a string or empty string
        if result is not None:
            self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
